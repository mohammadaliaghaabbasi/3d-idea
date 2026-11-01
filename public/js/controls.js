/**
 * PANODROME — 6DoF walk controls
 *
 *  WASD / arrows      walk on the floor plane (real parallax inside the displaced mesh)
 *  drag (mouse/touch) look around (yaw + pitch)
 *  wheel / trackpad   glide forward/back along the view vector (clamped)
 *  hold-to-walk pad   touch devices
 *
 * Movement is clamped to the room box from rooms_db.json (safe zone) so the
 * camera never leaves the reconstructed volume.
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
    this.walkSpeed = 2.3;         // m/s
    this.runFactor = 1.85;
    this.autoWalk = false;        // touch pad
    this._vel = { x: 0, z: 0 };

    this.box = { minX: -2, maxX: 2, minZ: -2, maxZ: 2, minY: 1.0, maxY: 2.4 };
    this.eyeY = 1.6;

    this._stepDist = 0;
    this._stepLen = 0.78;
    this.onStep = null;           // () => void

    this._down = null;            // {x, y, t, id, moved}
    this.onClick = null;          // (x, y) pointer click (screen px)

    this._fwd = new THREE.Vector3();
    this._flat = new THREE.Vector3();
    this._right = new THREE.Vector3();

    this._bind();
  }

  setRoom(room) {
    const s = room.room_shape, c = room.camera;
    const m = 0.45;
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
    // face the curated initial view
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

  update(dt) {
    if (!this.enabled) return;
    const cam = this.camera;

    // target velocity from keys
    cam.getWorldDirection(this._fwd);
    const flat = this._flat.set(this._fwd.x, 0, this._fwd.z);
    if (flat.lengthSq() < 1e-6) flat.set(0, 0, -1);
    flat.normalize();
    const right = this._right.set(-flat.z, 0, flat.x); // forward × up

    const k = this.keys;
    let x = 0, z = 0;
    if (k.has("KeyW") || k.has("ArrowUp") || this.autoWalk) z += 1;
    if (k.has("KeyS") || k.has("ArrowDown")) z -= 1;
    if (k.has("KeyA") || k.has("ArrowLeft")) x -= 1;
    if (k.has("KeyD") || k.has("ArrowRight")) x += 1;

    const speed = this.walkSpeed * (k.has("ShiftLeft") || k.has("ShiftRight") ? this.runFactor : 1);
    const tx = (flat.x * z + right.x * x), tz = (flat.z * z + right.z * x);
    const len = Math.hypot(tx, tz) || 1;
    const targetVX = (tx / len) * speed * (x || z ? 1 : 0);
    const targetVZ = (tz / len) * speed * (x || z ? 1 : 0);

    // velocity smoothing (this._vel is a plain {x,z} carrier)
    if (!this._vel) this._vel = { x: 0, z: 0 };
    const smooth = 1 - Math.exp(-dt * 11);
    this._vel.x += (targetVX - this._vel.x) * smooth;
    this._vel.z += (targetVZ - this._vel.z) * smooth;

    const px = cam.position.x, pz = cam.position.z;
    cam.position.x += this._vel.x * dt;
    cam.position.z += this._vel.z * dt;
    this._clampPosition();

    // footsteps by accumulated horizontal distance
    const moved = Math.hypot(cam.position.x - px, cam.position.z - pz);
    if (moved > 0.001) {
      this._stepDist += moved;
      if (this._stepDist >= this._stepLen * (this.runFactor > 1 && k.has("ShiftLeft") ? 1.35 : 1)) {
        this._stepDist = 0;
        this.onStep && this.onStep();
      }
    } else {
      this._stepDist = Math.max(0, this._stepDist - dt * 0.4); // decay
    }

    // orientation
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
      this._down = null;
      if (quick && this.onClick) this.onClick(e.clientX, e.clientY);
    };
    this._onWheel = (e) => {
      if (!this.enabled) return;
      e.preventDefault();
      const d = (e.deltaY < 0 ? 1 : -1) * 0.75;
      this.camera.getWorldDirection(this._fwd);
      this.camera.position.addScaledVector(this._fwd, d);
      // keep eye height comfortable while gliding
      this.camera.position.y = Math.min(Math.max(this.camera.position.y, this.box.minY), this.box.maxY);
      this._clampPosition();
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
