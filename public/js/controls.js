/**
 * PANODROME — Stage 1.5 · True First-Person Walking Controls
 *
 * REAL WALKING, NOT ZOOMING (locked 2026-11-02):
 *   · camera.fov is FIXED (68° desktop / 75° mobile) — set once by main.js,
 *     NEVER touched here. Walking = true translation of camera.position.x/z
 *     across the floor in real metres (a full room crossing), resolved
 *     against the collision world (collider.js) with sliding response.
 *   · Natural footstep head-bob: camera.position.y = 1.65 + 0.028·sin(bob),
 *     bob phase driven by metres travelled (one cycle every 0.65 m — the
 *     same law that triggers the soft footstep sound).
 *
 * Inputs:
 *   · drag            = look around
 *   · wheel           = walk forward / back (momentum, like real steps)
 *   · two-finger drag = walk forward / back (touch)
 *   · W A S D / arrows= game walking (A/D strafe, ←/→ turn)
 *   · double-tap      = walk TO the tapped floor point (raycast by main)
 *   · virtual joystick(touch HUD) = analog walking
 *   · reset button    = "بازگشت به مرکز فضا" — glide back to the capture point
 */
import * as THREE from "three";

export const EYE_HEIGHT = 1.65;   // player eye (m) — camera.y = EYE + bob
export const STEP_LEN = 0.65;     // m per footstep (audio + bob cycle)
const WALK_SPEED = 1.9;           // m/s hold-input speed
const BOOST_MAX = 4.2;            // m/s peak scroll momentum
const BOOST_DECAY = 2.1;          // 1/s exponential momentum decay
const ACCEL = 8.5;                // 1/s input acceleration smoothing
const BOB_AMP = 0.028;            // m head-bob amplitude
const TURN_SPEED = 1.7;           // rad/s arrow-key turn
const STOP_EPS = 0.04;            // m — arrived at walkTo target

export class WalkingControls {
  constructor(camera, dom) {
    this.camera = camera;
    this.dom = dom;
    this.enabled = false;

    // look
    this.yaw = 0;
    this.pitch = 0;
    this.sensitivity = 0.0031;

    // walk state
    this.pos = new THREE.Vector3();          // player position (y = floor logic)
    this.vel = new THREE.Vector2();          // world-space velocity m/s (x, z)
    this.boost = new THREE.Vector2();        // scroll momentum (x, z)
    this.keys = new Set();
    this.joy = { x: 0, y: 0 };               // joystick: x strafe, y forward (-1..1)
    this.walkTarget = null;                  // Vector3 | null (double-tap destination)
    this.start = new THREE.Vector3();        // room capture point (reset target)
    this.room = null;

    // bob / steps
    this.bobPhase = 0;
    this.travelled = 0;                      // metres walked this room
    this.onStep = null;                      // (material) fired every STEP_LEN m
    this.stepMaterial = "wood";

    // collision world (set per room via setWorld)
    this.world = null;
    this.onBump = null;                      // (bump) fired on real collisions

    this._pointers = new Map();
    this._down = null;
    this._lastTap = null;
    this._lookTween = null;
    this._resetTween = null;
    this._stepAccum = 0;

    this.onClick = null;                     // (x, y)
    this.onDouble = null;                    // (x, y)
    this._fwd = new THREE.Vector3();

    this._bind();
  }

  /* ------------------------------------------------------------ room setup */

  setRoom(room) {
    this.room = room;
    const c = room.camera;
    this.start.set(c.x, EYE_HEIGHT, c.z);
    this.pos.copy(this.start);
    this.vel.set(0, 0);
    this.boost.set(0, 0);
    this.walkTarget = null;
    this.travelled = 0;
    this.bobPhase = 0;
    this._stepAccum = 0;
    this.stepMaterial = room.floor_material || "wood";
    this.lookAtFraction(room.initial_view.facing);
    if (this._resetTween) { this._resetTween.kill(); this._resetTween = null; }
  }

  setWorld(world) { this.world = world; }

  /** Orient yaw/pitch toward a horizontal image fraction f (0..1). */
  lookAtFraction(f) {
    const phi = 2 * Math.PI * f;
    const dir = new THREE.Vector3(-Math.cos(phi), 0, Math.sin(phi));
    const target = this.pos.clone().add(dir);
    this.camera.position.copy(this.pos);
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

  /** Walk TO a world point on the floor (double-tap). */
  walkTo(point) {
    if (!this.world) return;
    const p = point.clone();
    p.y = 0;
    this.walkTarget = p;
  }

  /** "بازگشت به مرکز فضا" — glide back to the capture point. */
  resetView() {
    this.walkTarget = null;
    this.vel.set(0, 0);
    this.boost.set(0, 0);
    if (this._resetTween) this._resetTween.kill();
    const self = this;
    const from = this.pos.clone();
    const to = this.start.clone();
    const dist = Math.hypot(to.x - from.x, to.z - from.z);
    if (dist < 0.05) return;
    this._resetTween = gsap.to({ t: 0 }, {
      t: 1, duration: Math.min(1.4, 0.35 + dist * 0.22), ease: "power2.inOut",
      onUpdate() {
        const t = this.targets()[0].t;
        self.pos.x = from.x + (to.x - from.x) * t;
        self.pos.z = from.z + (to.z - from.z) * t;
      },
      onComplete() { self._resetTween = null; },
    });
  }

  get moved() { return Math.hypot(this.pos.x - this.start.x, this.pos.z - this.start.z) > 0.4; }
  get speed() { return this.vel.length(); }
  get fov() { return this.camera.fov; }   // fixed — walking NEVER zooms

  /* ------------------------------------------------------------ frame loop */

  update(dt) {
    const cam = this.camera;

    // ---- desired velocity from all inputs ----
    const wish = new THREE.Vector2(0, 0);   // world-space (x, z)

    if (this.enabled) {
      // keyboard: local axes → world
      let ix = 0, iz = 0;   // strafe, forward
      if (this.keys.has("KeyW") || this.keys.has("ArrowUp")) iz += 1;
      if (this.keys.has("KeyS") || this.keys.has("ArrowDown")) iz -= 1;
      if (this.keys.has("KeyA")) ix -= 1;
      if (this.keys.has("KeyD")) ix += 1;
      if (this.keys.has("ArrowLeft")) this.yaw += TURN_SPEED * dt;
      if (this.keys.has("ArrowRight")) this.yaw -= TURN_SPEED * dt;

      // joystick: local axes → world
      ix += this.joy.x;
      iz += this.joy.y;

      const len = Math.hypot(ix, iz);
      if (len > 1e-4) {
        const s = WALK_SPEED * Math.min(1, len);
        const sinY = Math.sin(this.yaw), cosY = Math.cos(this.yaw);
        // camera forward (horizontal) = (-sin(yaw), -cos(yaw)); right = (cos, -sin)
        wish.x += (ix * cosY - iz * sinY) * s;
        wish.y += (iz * -cosY + ix * -sinY) * s;
      }

      // double-tap destination
      if (this.walkTarget) {
        const dx = this.walkTarget.x - this.pos.x;
        const dz = this.walkTarget.z - this.pos.z;
        const d = Math.hypot(dx, dz);
        if (d < STOP_EPS) {
          this.walkTarget = null;
        } else {
          const s = WALK_SPEED * Math.min(1, d / 0.6);
          wish.x += (dx / d) * s;
          wish.y += (dz / d) * s;
        }
      }
    }

    // smooth acceleration toward wish + scroll momentum
    const target = wish.clone().add(this.boost);
    this.vel.x += (target.x - this.vel.x) * Math.min(1, dt * ACCEL);
    this.vel.y += (target.y - this.vel.y) * Math.min(1, dt * ACCEL);
    const boostDecay = Math.exp(-BOOST_DECAY * dt);
    this.boost.multiplyScalar(boostDecay);
    if (this.boost.lengthSq() < 1e-4) this.boost.set(0, 0);

    // ---- integrate + slide against the collision world ----
    const bx = this.pos.x, bz = this.pos.z;
    this.pos.x += this.vel.x * dt;
    this.pos.z += this.vel.y * dt;
    let bump = null;
    if (this.world) {
      bump = this.world.resolve(this.pos, this.vel);
      // head-on hit cancels the auto-walk; grazes keep sliding toward it
      if (this.walkTarget && bump && bump.impact > 0.7) this.walkTarget = null;
    }
    const movedDist = Math.hypot(this.pos.x - bx, this.pos.z - bz);

    // ---- metres travelled → bob + footsteps ----
    this.travelled += movedDist;
    this._stepAccum += movedDist;
    if (this._stepAccum >= STEP_LEN) {
      this._stepAccum -= STEP_LEN;
      this.onStep && this.onStep(this.stepMaterial);
    }
    const spd = this.vel.length();
    this.bobPhase += movedDist * (Math.PI / STEP_LEN);
    const bobAmt = Math.min(1, spd / 1.1);
    const bob = BOB_AMP * Math.sin(this.bobPhase) * bobAmt;

    // ---- apply to camera (FOV stays FIXED — no zooming, ever) ----
    cam.position.set(this.pos.x, EYE_HEIGHT + bob, this.pos.z);
    cam.rotation.order = "YXZ";
    cam.rotation.set(this.pitch, this.yaw, 0);

    if (bump && this.onBump) this.onBump(bump);
    return bump;
  }

  /* ------------------------------------------------------------ events */

  _bind() {
    const dom = this.dom;

    this._onKeyDown = (e) => {
      if (e.code === "ArrowUp" || e.code === "ArrowDown" || e.code === "ArrowLeft" || e.code === "ArrowRight" || e.code === "Space") e.preventDefault();
      this.keys.add(e.code);
    };
    this._onKeyUp = (e) => this.keys.delete(e.code);
    this._onBlur = () => this.keys.clear();

    this._onPointerDown = (e) => {
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (this._pointers.size === 2) {
        this._down = null;                     // two-finger = walk, not look
        return;
      }
      if (!this.enabled) return;
      this._down = { x: e.clientX, y: e.clientY, t: performance.now(), moved: 0, id: e.pointerId };
      try { dom.setPointerCapture(e.pointerId); } catch (err) {}
    };

    this._onPointerMove = (e) => {
      const prev = this._pointers.get(e.pointerId);

      // two-finger vertical drag = walk forward / back (along the look direction)
      if (this._pointers.size === 2 && prev) {
        const dy = e.clientY - prev.y;
        if (this.enabled && Math.abs(dy) > 0.5) {
          const sinY = Math.sin(this.yaw), cosY = Math.cos(this.yaw);
          this._addBoost(-sinY * -dy * 0.011, -cosY * -dy * 0.011);
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
      if (!this._down || e.pointerId !== this._down.id) return;
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
      const step = e.deltaMode === 1 ? e.deltaY * 18 : e.deltaY;
      // scroll up = walk forward, along the current look direction
      const sinY = Math.sin(this.yaw), cosY = Math.cos(this.yaw);
      this._addBoost(-sinY * -step * 0.0075, -cosY * -step * 0.0075);
    };

    addEventListener("keydown", this._onKeyDown);
    addEventListener("keyup", this._onKeyUp);
    addEventListener("blur", this._onBlur);
    dom.addEventListener("pointerdown", this._onPointerDown);
    dom.addEventListener("pointermove", this._onPointerMove);
    dom.addEventListener("pointerup", this._onPointerUp);
    dom.addEventListener("pointercancel", this._onPointerUp);
    dom.addEventListener("wheel", this._onWheel, { passive: false });
  }

  /** Add scroll/two-finger momentum (m/s), clamped to BOOST_MAX. */
  _addBoost(x, z) {
    this.boost.x = THREE.MathUtils.clamp(this.boost.x + x, -BOOST_MAX, BOOST_MAX);
    this.boost.y = THREE.MathUtils.clamp(this.boost.y + z, -BOOST_MAX, BOOST_MAX);
    this.walkTarget = null;
  }

  dispose() {
    removeEventListener("keydown", this._onKeyDown);
    removeEventListener("keyup", this._onKeyUp);
    removeEventListener("blur", this._onBlur);
    const dom = this.dom;
    dom.removeEventListener("pointerdown", this._onPointerDown);
    dom.removeEventListener("pointermove", this._onPointerMove);
    dom.removeEventListener("pointerup", this._onPointerUp);
    dom.removeEventListener("pointercancel", this._onPointerUp);
    dom.removeEventListener("wheel", this._onWheel);
  }
}
