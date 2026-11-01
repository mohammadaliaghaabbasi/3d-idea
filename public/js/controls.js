/**
 * PANODROME — 6DoF walk controls v2 (Phase 2.5)
 *
 *  WASD / arrows          walk on the floor plane (real parallax)
 *  drag (mouse/touch)     look around (yaw + pitch)
 *  wheel / trackpad       smooth walk forward/back along the look vector
 *  double-click / tap     glide 1.5–2.5 m toward the tapped point (GSAP)
 *  on-screen rocker       thumb walk pad on touch devices (fwd / back)
 *
 * Every source of horizontal motion — keys, wheel, glide, rocker and the
 * portal-transition glide — feeds the same step accumulator, so footsteps
 * always match the walking. A subtle head-bob rides on top of motion.
 * Movement is clamped to the room box from rooms_db.json (safe zone).
 */
import * as THREE from "three";

export class SixDofControls {
  /**
   * @param {THREE.PerspectiveCamera} camera
   * @param {HTMLElement} dom element receiving pointer events
   */
  constructor(camera, dom) {
    this.camera = camera;
    this.dom = dom;
    this.enabled = false;

    this.keys = new Set();
    this.yaw = 0;
    this.pitch = 0;
    this.sensitivity = 0.0031;
    this.walkSpeed = 2.5;         // m/s
    this.runFactor = 1.85;
    this.rocker = 0;              // -1..1  (mobile thumb pad)
    this._wheelVel = 0;           // m/s impulse from the wheel
    this._vel = { x: 0, z: 0 };
    this._gliding = false;

    this.box = { minX: -2, maxX: 2, minZ: -2, maxZ: 2, minY: 1.0, maxY: 2.4 };
    this.eyeY = 1.6;

    this._stepDist = 0;
    this._stepLen = 0.74;
    this.onStep = null;           // () => void  (footstep)

    this._bobPhase = 0;
    this._lastBob = 0;

    this._down = null;            // {x, y, t, id, moved}
    this._lastTap = null;         // {t, x, y}
    this.onClick = null;          // (x, y) single tap/click
    this.onDouble = null;         // (x, y) double tap/click → walk there

    this._fwd = new THREE.Vector3();
    this._flat = new THREE.Vector3();
    this._right = new THREE.Vector3();

    this._bind();
  }

  setRoom(room) {
    const s = room.room_shape, c = room.camera;
    const m = 0.4;
    this.box = {
      minX: -s.width / 2 + m,
      maxX: s.width / 2 - m,
      minZ: -s.depth / 2 + m,
      maxZ: s.depth / 2 - m,
      minY: Math.max(0.9, this.eyeY - 0.65),
      maxY: Math.min(s.height - 0.35, 4.2),
    };
    this.camera.position.set(c.x, c.y, c.z);
    this._clampPosition();
    this.lookAtFraction(room.initial_view.facing);
  }

  /** Orient yaw/pitch to look toward horizontal image fraction f (0..1). */
  lookAtFraction(f) {
    const phi = 2 * Math.PI * f;
    const dir = new THREE.Vector3(-Math.cos(phi), 0, Math.sin(phi));
    const target = this.camera.position.clone().add(dir);
    this.camera.lookAt(target);
    this.camera.rotation.order = "YXZ";
    this.yaw = this.camera.rotation.y;
    this.pitch = this.camera.rotation.x;
  }

  /* ------------------------------------------------------------ click-to-walk */

  /** Glide `metres` toward a world direction (horizontal), GSAP-eased. */
  glide(dirX, dirZ, metres) {
    if (this._gliding || !this.enabled) return;
    const len = Math.hypot(dirX, dirZ) || 1;
    const nx = dirX / len, nz = dirZ / len;
    const px = this.camera.position.x, pz = this.camera.position.z;
    let tx = px + nx * metres, tz = pz + nz * metres;
    tx = Math.min(Math.max(tx, this.box.minX), this.box.maxX);
    tz = Math.min(Math.max(tz, this.box.minZ), this.box.maxZ);
    const dist = Math.hypot(tx - px, tz - pz);
    if (dist < 0.3) return;
    this._gliding = true;
    const pos = this.camera.position;
    const lx = pos.x, lz = pos.z;
    gsap.to(pos, {
      x: tx, z: tz,
      duration: Math.min(1.6, 0.45 + dist * 0.32),
      ease: "power2.inOut",
      onUpdate: () => {
        const mx = pos.x - (this._glx ?? lx), mz = pos.z - (this._glz ?? lz);
        this._glx = pos.x; this._glz = pos.z;
        this._accumulateSteps(Math.hypot(mx, mz));
      },
      onComplete: () => {
        this._gliding = false;
        this._glx = this._glz = undefined;
      },
    });
  }

  _accumulateSteps(moved) {
    if (moved <= 0) return;
    this._stepDist += moved;
    if (this._stepDist >= this._stepLen) {
      this._stepDist -= this._stepLen;
      this.onStep && this.onStep();
    }
  }

  /* ------------------------------------------------------------ frame loop */

  update(dt) {
    const cam = this.camera;
    if (this._lastBob !== 0) { cam.position.y -= this._lastBob; this._lastBob = 0; }
    if (!this.enabled) {
      cam.rotation.order = "YXZ";
      cam.rotation.set(this.pitch, this.yaw, 0);
      return;
    }

    cam.getWorldDirection(this._fwd);
    const flat = this._flat.set(this._fwd.x, 0, this._fwd.z);
    if (flat.lengthSq() < 1e-6) flat.set(0, 0, -1);
    flat.normalize();
    const right = this._right.set(-flat.z, 0, flat.x);

    const k = this.keys;
    let x = 0, z = 0;
    if (k.has("KeyW") || k.has("ArrowUp")) z += 1;
    if (k.has("KeyS") || k.has("ArrowDown")) z -= 1;
    if (k.has("KeyA") || k.has("ArrowLeft")) x -= 1;
    if (k.has("KeyD") || k.has("ArrowRight")) x += 1;
    z += this.rocker;                      // mobile thumb rocker
    z += THREE.MathUtils.clamp(this._wheelVel, -1, 1);  // wheel walk
    this._wheelVel *= Math.exp(-dt * 4.2); // wheel impulse decays
    if (Math.abs(this._wheelVel) < 0.02) this._wheelVel = 0;

    const speed = this.walkSpeed * (k.has("ShiftLeft") || k.has("ShiftRight") ? this.runFactor : 1);
    const tx = flat.x * z + right.x * x;
    const tz = flat.z * z + right.z * x;
    const len = Math.hypot(tx, tz) || 1;
    const mag = Math.min(1, Math.hypot(x, z) + Math.abs(this.rocker) + Math.min(1, Math.abs(this._wheelVel)));
    const targetVX = (tx / len) * speed * mag;
    const targetVZ = (tz / len) * speed * mag;

    const smooth = 1 - Math.exp(-dt * 11);
    this._vel.x += (targetVX - this._vel.x) * smooth;
    this._vel.z += (targetVZ - this._vel.z) * smooth;

    const px = cam.position.x, pz = cam.position.z;
    if (!this._gliding) {
      cam.position.x += this._vel.x * dt;
      cam.position.z += this._vel.z * dt;
    } else {
      this._vel.x = this._vel.z = 0;
    }
    this._clampPosition();

    // footsteps from every kind of motion (glide feeds _accumulateSteps itself)
    if (!this._gliding) {
      const moved = Math.hypot(cam.position.x - px, cam.position.z - pz);
      if (moved > 0.001) {
        this._accumulateSteps(moved);
      } else {
        this._stepDist = Math.max(0, this._stepDist - dt * 0.4);
      }
    }

    // subtle head-bob while walking
    const speedNow = Math.hypot(this._vel.x, this._vel.z) + (this._gliding ? 1.2 : 0);
    if (speedNow > 0.25) {
      this._bobPhase += dt * (4.6 + speedNow * 1.6);
      this._lastBob = Math.sin(this._bobPhase) * 0.032 * Math.min(1, speedNow / 2);
      cam.position.y += this._lastBob;
    } else {
      this._bobPhase = 0;
    }

    cam.rotation.order = "YXZ";
    cam.rotation.set(this.pitch, this.yaw, 0);
  }

  _clampPosition() {
    const p = this.camera.position;
    p.x = Math.min(Math.max(p.x, this.box.minX), this.box.maxX);
    p.z = Math.min(Math.max(p.z, this.box.minZ), this.box.maxZ);
    p.y = Math.min(Math.max(p.y, this.box.minY), this.box.maxY);
  }

  _bind() {
    const dom = this.dom;
    this._onKeyDown = (e) => {
      if (e.repeat) return;
      this.keys.add(e.code);
      if (["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"].includes(e.code)) e.preventDefault();
    };
    this._onKeyUp = (e) => this.keys.delete(e.code);
    this._onBlur = () => this.keys.clear();

    this._onPointerDown = (e) => {
      if (!this.enabled) return;
      this._down = { x: e.clientX, y: e.clientY, t: performance.now(), moved: 0, id: e.pointerId };
      try { dom.setPointerCapture(e.pointerId); } catch (err) {}
    };
    this._onPointerMove = (e) => {
      if (!this.enabled || !this._down || e.pointerId !== this._down.id) return;
      const dx = e.clientX - this._down.x, dy = e.clientY - this._down.y;
      this._down.moved += Math.abs(dx) + Math.abs(dy);
      this._down.x = e.clientX; this._down.y = e.clientY;
      this.yaw -= dx * this.sensitivity;
      this.pitch -= dy * this.sensitivity;
      this.pitch = Math.min(Math.max(this.pitch, -1.35), 1.35);
    };
    this._onPointerUp = (e) => {
      if (!this._down || e.pointerId !== this._down.id) return;
      const quick = performance.now() - this._down.t < 350 && this._down.moved < 8;
      const { x, y } = this._down;
      this._down = null;
      if (!quick) return;
      const now = performance.now();
      const lt = this._lastTap;
      this._lastTap = { t: now, x, y };
      if (lt && now - lt.t < 320 && Math.hypot(x - lt.x, y - lt.y) < 32) {
        this._lastTap = null;
        this.onDouble && this.onDouble(x, y);      // double tap → walk
      } else {
        this.onClick && this.onClick(x, y);
      }
    };
    this._onWheel = (e) => {
      if (!this.enabled) return;
      e.preventDefault();
      const step = e.deltaMode === 1 ? e.deltaY / 18 : e.deltaY;
      this._wheelVel += (step < 0 ? 1 : -1) * Math.min(1.4, Math.abs(step) / 90 + 0.5);
      this._wheelVel = THREE.MathUtils.clamp(this._wheelVel, -2.4, 2.4);
    };

    window.addEventListener("keydown", this._onKeyDown, { passive: false });
    window.addEventListener("keyup", this._onKeyUp);
    window.addEventListener("blur", this._onBlur);
    dom.addEventListener("pointerdown", this._onPointerDown);
    dom.addEventListener("pointermove", this._onPointerMove);
    dom.addEventListener("pointerup", this._onPointerUp);
    dom.addEventListener("pointercancel", this._onPointerUp);
    dom.addEventListener("wheel", this._onWheel, { passive: false });
  }

  dispose() {
    const dom = this.dom;
    window.removeEventListener("keydown", this._onKeyDown);
    window.removeEventListener("keyup", this._onKeyUp);
    window.removeEventListener("blur", this._onBlur);
    dom.removeEventListener("pointerdown", this._onPointerDown);
    dom.removeEventListener("pointermove", this._onPointerMove);
    dom.removeEventListener("pointerup", this._onPointerUp);
    dom.removeEventListener("pointercancel", this._onPointerUp);
    dom.removeEventListener("wheel", this._onWheel);
  }
}
