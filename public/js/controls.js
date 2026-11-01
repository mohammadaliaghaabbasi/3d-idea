/**
 * PANODROME — Stage 1 · Optical Walk Controls
 *
 * How world-class architectural viewers (Kuula Pro, Matterport, VisionOS)
 * create the feel of stepping closer inside a single 360° panorama WITHOUT
 * ever bending a straight line:
 *
 *   1. MICRO-PARALLAX  — the camera shifts at most 0.18 m along the inspect
 *      direction (anchored at the point you chose), a truthful little lean-in.
 *   2. OPTICAL FOCAL GLIDE — camera.fov glides 78° (stepped-back overview)
 *      ↔ 70° (standing) ↔ 42° (close inspection) driven by a damped spring,
 *      so every vertical stays plumb while you genuinely feel the approach.
 *
 * Inputs: drag = look · wheel = walk · two-finger vertical drag = walk ·
 * double-tap/double-click a point = turn toward it and glide in ·
 * on-screen thumb pad (touch) = walk · tap empty space while glided = step
 * back to centre · ⛶ / scrolling back through 0 = "بازگشت به مرکز فضا".
 *
 * STAGE 1 IS SILENT BY DESIGN — no synthetic footsteps, no oscillator audio.
 */
import * as THREE from "three";

const FOV_REST = 70;      // standing at the panorama centre
const FOV_INSPECT = 42;   // close inspection
const FOV_WIDE = 78;      // stepped-back overview
const PARALLAX_MAX = 0.18; // m — subtle, truthful lean-in
const SPRING_STIFF = 46;
const SPRING_DAMP = 9.0;

function fovOf(w) {
  return w >= 0
    ? FOV_REST + (FOV_INSPECT - FOV_REST) * w
    : FOV_REST + (FOV_WIDE - FOV_REST) * (-w);
}

export class OpticalControls {
  constructor(camera, dom) {
    this.camera = camera;
    this.dom = dom;
    this.enabled = false;

    this.yaw = 0;
    this.pitch = 0;
    this.sensitivity = 0.0031;

    /* optical walk state — w ∈ [-1, 1] (see header) */
    this.w = 0;
    this.wTarget = 0;
    this.wVel = 0;
    this.anchorDir = null;          // horizontal inspect direction (Vector3 | null)

    this.base = new THREE.Vector3(); // pano centre (room camera)
    this.pad = 0;                    // thumb pad: -1..1 while held

    this._pointers = new Map();      // active pointers (for two-finger walk)
    this._down = null;               // single-pointer look/drag state
    this._lastTap = null;
    this._lookTween = null;

    this.onClick = null;             // (x, y)
    this.onDouble = null;            // (x, y, worldDir|null)

    this._fwd = new THREE.Vector3();
    this._tmp = new THREE.Vector3();

    this._bind();
  }

  /* ------------------------------------------------------------ room setup */

  setRoom(room) {
    const c = room.camera;
    this.base.set(c.x, c.y, c.z);
    // snap to the pano centre — the sphere renders pano-exact from here
    this.camera.position.copy(this.base);
    this.w = 0;
    this.wTarget = 0;
    this.wVel = 0;
    this.anchorDir = null;
    this.lookAtFraction(room.initial_view.facing);
  }

  /** Orient yaw/pitch toward a horizontal image fraction f (0..1). */
  lookAtFraction(f) {
    const phi = 2 * Math.PI * f;
    const dir = new THREE.Vector3(-Math.cos(phi), 0, Math.sin(phi));
    const target = this.camera.position.clone().add(dir);
    this.camera.lookAt(target);
    this.camera.rotation.order = "YXZ";
    this.yaw = this.camera.rotation.y;
    this.pitch = this.camera.rotation.x;
  }

  /** Smoothly rotate the camera toward a world direction (GSAP, shortest arc). */
  lookToward(dir) {
    const d = dir.clone().normalize();
    const targetYaw = Math.atan2(-d.x, -d.z);
    const targetPitch = THREE.MathUtils.clamp(Math.asin(THREE.MathUtils.clamp(d.y, -1, 1)), -1.2, 1.2);
    let dy = targetYaw - this.yaw;
    while (dy > Math.PI) dy -= Math.PI * 2;
    while (dy < -Math.PI) dy += Math.PI * 2;
    if (this._lookTween) this._lookTween.kill();
    const fromYaw = this.yaw, fromPitch = this.pitch;
    const self = this;
    this._lookTween = gsap.to({ t: 0 }, {
      t: 1, duration: 0.85, ease: "power2.inOut",
      onUpdate() {
        const t = this.targets()[0].t;
        self.yaw = fromYaw + dy * t;
        self.pitch = fromPitch + (targetPitch - fromPitch) * t;
      },
      onComplete() { self._lookTween = null; },
    });
  }

  /* ------------------------------------------------------------ walk API */

  /** Glide to an inspection amount (clamped -1..1). anchorDir optional. */
  glideTo(wTarget, anchorDir = null) {
    this.wTarget = THREE.MathUtils.clamp(wTarget, -1, 1);
    if (anchorDir) {
      this.anchorDir = anchorDir.clone().setY(0).normalize();
    }
  }

  /** "بازگشت به مرکز فضا" — step back to the pano centre at fov 70. */
  resetView() {
    this.wTarget = 0;
    this.anchorDir = null;
  }

  get glided() { return Math.abs(this.w) > 0.05 || Math.abs(this.wTarget) > 0.05; }
  get fov() { return this.camera.fov; }

  /* ------------------------------------------------------------ frame loop */

  update(dt) {
    const cam = this.camera;

    // thumb pad drives wTarget while held (rate-limited, stays when released)
    if (this.pad !== 0) {
      this.wTarget = THREE.MathUtils.clamp(this.wTarget + this.pad * dt * 1.15, -1, 1);
    }

    // damped spring on w — the cinematic optical glide
    this.wVel += (this.wTarget - this.w) * SPRING_STIFF * dt;
    this.wVel *= Math.exp(-SPRING_DAMP * dt);
    this.w = THREE.MathUtils.clamp(this.w + this.wVel * dt, -1, 1);

    if (this.enabled) {
      // anchor: capture the look direction the moment the lean-in begins
      if (this.w > 0.02 && !this.anchorDir) {
        cam.getWorldDirection(this._fwd);
        this.anchorDir = this._fwd.clone().setY(0).normalize();
        if (this.anchorDir.lengthSq() < 1e-6) this.anchorDir.set(0, 0, -1);
      }
      if (this.w <= 0.01) this.anchorDir = null;

      // micro-parallax (max 0.18 m) — only while leaning in
      cam.position.copy(this.base);
      if (this.w > 0 && this.anchorDir) {
        cam.position.addScaledVector(this.anchorDir, PARALLAX_MAX * this.w);
      }

      // optical focal glide
      const fov = fovOf(this.w);
      if (Math.abs(cam.fov - fov) > 0.01) {
        cam.fov = fov;
        cam.updateProjectionMatrix();
      }
    }

    cam.rotation.order = "YXZ";
    cam.rotation.set(this.pitch, this.yaw, 0);
  }

  /* ------------------------------------------------------------ events */

  _bind() {
    const dom = this.dom;

    this._onPointerDown = (e) => {
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (this._pointers.size === 2) {
        this._down = null;                       // two-finger = walk, not look
        return;
      }
      if (!this.enabled) return;
      this._down = { x: e.clientX, y: e.clientY, t: performance.now(), moved: 0, id: e.pointerId };
      try { dom.setPointerCapture(e.pointerId); } catch (err) {}
    };

    this._onPointerMove = (e) => {
      const prev = this._pointers.get(e.pointerId);

      // two-finger vertical drag = optical walk
      if (this._pointers.size === 2 && prev) {
        const dy = e.clientY - prev.y;
        if (this.enabled && Math.abs(dy) > 0.5) {
          this.wTarget = THREE.MathUtils.clamp(this.wTarget - dy * 0.004, -1, 1);
        }
        prev.x = e.clientX; prev.y = e.clientY;
        return;
      }

      if (!this.enabled || !this._down || e.pointerId !== this._down.id) return;
      const dx = e.clientX - this._down.x, dy = e.clientY - this._down.y;
      this._down.moved += Math.abs(dx) + Math.abs(dy);
      this._down.x = e.clientX; this._down.y = e.clientY;
      this.yaw -= dx * this.sensitivity;
      this.pitch -= dy * this.sensitivity;
      this.pitch = THREE.MathUtils.clamp(this.pitch, -1.35, 1.35);
    };

    this._onPointerUp = (e) => {
      this._pointers.delete(e.pointerId);
      if (!this._down || e.pointerId !== this._down.id) { return; }
      const quick = performance.now() - this._down.t < 350 && this._down.moved < 8;
      const { x, y } = this._down;
      this._down = null;
      if (!quick || !this.enabled) return;

      const now = performance.now();
      const lt = this._lastTap;
      this._lastTap = { t: now, x, y };
      if (lt && now - lt.t < 320 && Math.hypot(x - lt.x, y - lt.y) < 32) {
        this._lastTap = null;
        this.onDouble && this.onDouble(x, y);
      } else {
        this.onClick && this.onClick(x, y);
      }
    };

    this._onWheel = (e) => {
      if (!this.enabled) return;
      e.preventDefault();
      const step = e.deltaMode === 1 ? e.deltaY / 18 : e.deltaY;
      const dir = step < 0 ? 1 : -1;               // scroll up = walk in
      this.wTarget = THREE.MathUtils.clamp(this.wTarget + dir * Math.min(0.22, Math.abs(step) / 220 + 0.07), -1, 1);
    };

    dom.addEventListener("pointerdown", this._onPointerDown);
    dom.addEventListener("pointermove", this._onPointerMove);
    dom.addEventListener("pointerup", this._onPointerUp);
    dom.addEventListener("pointercancel", this._onPointerUp);
    dom.addEventListener("wheel", this._onWheel, { passive: false });
  }

  dispose() {
    const dom = this.dom;
    dom.removeEventListener("pointerdown", this._onPointerDown);
    dom.removeEventListener("pointermove", this._onPointerMove);
    dom.removeEventListener("pointerup", this._onPointerUp);
    dom.removeEventListener("pointercancel", this._onPointerUp);
    dom.removeEventListener("wheel", this._onWheel);
  }
}
