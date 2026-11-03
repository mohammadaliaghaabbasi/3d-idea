/**
 * PANODROME — Stage 2.1 · TRUE-WALK CONTROLS (owner order 2026-11-03
 * "Kill the Fake FOV Zoom!")
 * ============================================================================
 * ONE walk engine for ALL 11 rooms — real multi-metre 6DoF walking:
 *   · camera.fov is LOCKED (68° desktop / 75° touch) during walking, in every
 *     room, in every mode.  The 72°↔52° step-glide FOV pulse is DELETED —
 *     walking moves camera.position through the true-3D architectural
 *     scene, never a lens zoom.
 *   · WASD / arrows · virtual joystick · scroll wheel + two-finger drag =
 *     real strides · double-tap floor = walk TO the point.
 *   · Real sliding collision against the room's Box3/cylinder furniture
 *     world (collider.js) with bump events + acoustic footsteps + head-bob.
 *   · 360° PHOTO VIEW (pano rooms): the camera pins to the optical capture
 *     station and looks around freely; any walk input fires onWalkIntent →
 *     main crossfades (350 ms) into the aligned true-3D walk scene.
 */
import * as THREE from "three";

export const EYE_HEIGHT = 1.65;   // m — player eye (y = EYE + bob)
export const STEP_LEN = 0.65;     // m per footstep (audio + bob cycle)
const WALK_SPEED = 1.55;          // m/s virtual walk speed (calm museum pace)
const BOOST_MAX = 3.0;            // m/s peak scroll momentum
const BOOST_DECAY = 2.1;          // 1/s exponential momentum decay
const ACCEL = 8.5;                // 1/s input acceleration smoothing
const BOB_AMP = 0.018;            // m head-bob amplitude (subtle, physical)
const TURN_SPEED = 1.7;           // rad/s arrow-key turn
const STOP_EPS = 0.05;            // m — arrived at walkTo target

export const FOV_BASE = matchMedia("(pointer: coarse)").matches ? 75 : 68;

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
    this.mode = "free";                       // single true-walk mode everywhere
    this.origin = new THREE.Vector3();        // walk spawn (x, EYE, z)
    this.photoStation = new THREE.Vector3();  // 360° capture point
    this.photo = false;                       // pinned at the photo station?
    this.pos = new THREE.Vector3();           // the player body (x/z on the floor)
    this.vel = new THREE.Vector2();
    this.boost = new THREE.Vector2();
    this.keys = new Set();
    this.joy = { x: 0, y: 0 };
    this.walkTarget = null;
    this.start = new THREE.Vector3();          // reset target (== origin xz)
    this.room = null;
    this.onWalkIntent = null;                  // fired when photo mode gets walk input

    // bob / steps
    this.bobPhase = 0;
    this.travelled = 0;
    this.maxDisp = 0;                        // farthest the body reached from spawn
    this.onStep = null;
    this.stepMaterial = "wood";
    this.minFovSeen = FOV_BASE;
    this.maxFovSeen = FOV_BASE;
    this.maxOffsetSeen = 0;

    // collision world
    this.world = null;
    this.onBump = null;

    this._pointers = new Map();
    this._down = null;
    this._lastTap = null;
    this._lookTween = null;
    this._resetTween = null;
    this._stepAccum = 0;
    this._intentFired = false;

    this.onClick = null;
    this.onDouble = null;

    this._bind();
  }

  /* ------------------------------------------------------------ room setup */

  setRoom(room) {
    this.room = room;
    const c = room.camera;
    this.mode = "free";
    this.origin.set(c.x, EYE_HEIGHT, c.z);
    this.photoStation.set(c.x, c.y, c.z);
    this.start.set(c.x, 0, c.z);
    this.pos.set(c.x, 0, c.z);
    this.vel.set(0, 0);
    this.boost.set(0, 0);
    this.walkTarget = null;
    this.travelled = 0;
    this.maxDisp = 0;
    this.bobPhase = 0;
    this._stepAccum = 0;
    this._intentFired = false;
    this.photo = false;
    this.minFovSeen = FOV_BASE;
    this.maxFovSeen = FOV_BASE;
    this.maxOffsetSeen = 0;
    this.stepMaterial = room.floor_material || "wood";
    this.lookAtFraction(room.initial_view.facing);
    if (this._resetTween) { this._resetTween.kill(); this._resetTween = null; }
  }

  setWorld(world) { this.world = world; }

  /* ------------------------------------------------------------ view modes */

  /** Pin the camera to the 360° capture station (photo reference view). */
  enterPhoto() {
    this.photo = true;
    this.walkTarget = null;
    this._pendingWalk = null;
    this.vel.set(0, 0);
    this.boost.set(0, 0);
    this._intentFired = false;
  }

  /** Resume true walking (after the crossfade). */
  exitPhoto() {
    this.photo = false;
    this._intentFired = false;
    // a walk command that ARRIVED during photo mode continues after the
    // crossfade — the user asked to walk, so they keep walking
    if (this._pendingWalk) {
      this.walkTarget = this._pendingWalk;
      this._pendingWalk = null;
    }
  }

  /* ------------------------------------------------------------ walk API */

  walkTo(point) {
    if (!this.world) return null;
    const p = point.clone();
    p.y = 0;
    const b = this.world.bounds;
    if (b) {
      p.x = THREE.MathUtils.clamp(p.x, b.minX, b.maxX);
      p.z = THREE.MathUtils.clamp(p.z, b.minZ, b.maxZ);
    }
    if (this.photo) {
      this._pendingWalk = p;        // fires after the crossfade resumes walk
      this._fireIntent();
      return null;
    }
    this.walkTarget = p;
    return p;
  }

  /** "بازگشت به مرکز فضا" — glide the body home. */
  resetView() {
    if (this.photo) return;
    this.walkTarget = null;
    this.vel.set(0, 0);
    this.boost.set(0, 0);
    if (this._resetTween) this._resetTween.kill();
    // RESOLVED home: push the capture point out of any collider exclusion zone
    // first (a spawn can legally sit ON a zone boundary — e.g. a coffee table
    // at the capture station) — otherwise the glide-home tween fights the
    // resolver frame by frame and the body jitters with phantom footsteps
    const to = new THREE.Vector3(this.start.x, 0, this.start.z);
    if (this.world) {
      const v0 = new THREE.Vector2();
      this.world.resolve(to, v0);
    }
    const self = this;
    const from = this.pos.clone();
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

  /** The position doorway walk-ins and proximity FX measure against. */
  effectivePos() { return this.pos; }

  cameraOffset() {
    const dx = this.camera.position.x - this.photoStation.x;
    const dy = this.camera.position.y - this.photoStation.y;
    const dz = this.camera.position.z - this.photoStation.z;
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  get moved() { return Math.hypot(this.pos.x - this.start.x, this.pos.z - this.start.z) > 0.4; }
  get speed() { return this.vel.length(); }
  get fovCur() { return this.camera.fov; }
  get fovMust() { return FOV_BASE; }

  lookAtFraction(f) {
    const phi = 2 * Math.PI * f;
    const dir = new THREE.Vector3(-Math.cos(phi), 0, Math.sin(phi));
    const target = this.pos.clone().add(dir);
    this.camera.position.copy(this.pos).setY(EYE_HEIGHT);
    this.camera.lookAt(target);
    this.camera.rotation.order = "YXZ";
    this.yaw = this.camera.rotation.y;
    this.pitch = this.camera.rotation.x;
  }

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

  _fireIntent() {
    if (!this._intentFired) {
      this._intentFired = true;
      this.onWalkIntent && this.onWalkIntent();
    }
  }

  /* ------------------------------------------------------------ frame loop */

  update(dt) {
    const cam = this.camera;

    // ---- FOV LAW: locked, always, everywhere (no zoom-pulse hack) ----
    if (Math.abs(cam.fov - FOV_BASE) > 0.005) {
      cam.fov = FOV_BASE;
      cam.updateProjectionMatrix();
    }
    this.minFovSeen = Math.min(this.minFovSeen, cam.fov);
    this.maxFovSeen = Math.max(this.maxFovSeen, cam.fov);

    // ---- 360° photo mode: pinned at the capture station, look only ----
    if (this.photo) {
      // the virtual joystick writes into this.joy directly — an active
      // push means the user wants to WALK → fire the crossfade intent
      if (Math.hypot(this.joy.x, this.joy.y) > 0.14) this._fireIntent();
      this.vel.set(0, 0);
      this.boost.set(0, 0);
      cam.position.copy(this.photoStation);
      cam.rotation.order = "YXZ";
      cam.rotation.set(this.pitch, this.yaw, 0);
      return null;
    }

    // ---- desired velocity from all inputs ----
    const wish = new THREE.Vector2(0, 0);
    if (this.enabled) {
      let ix = 0, iz = 0;
      if (this.keys.has("KeyW") || this.keys.has("ArrowUp")) iz += 1;
      if (this.keys.has("KeyS") || this.keys.has("ArrowDown")) iz -= 1;
      if (this.keys.has("KeyA")) ix -= 1;
      if (this.keys.has("KeyD")) ix += 1;
      if (this.keys.has("ArrowLeft")) this.yaw += TURN_SPEED * dt;
      if (this.keys.has("ArrowRight")) this.yaw -= TURN_SPEED * dt;
      ix += this.joy.x;
      iz += this.joy.y;
      const len = Math.hypot(ix, iz);
      if (len > 1e-4) {
        const s = WALK_SPEED * Math.min(1, len);
        const sinY = Math.sin(this.yaw), cosY = Math.cos(this.yaw);
        wish.x += (ix * cosY - iz * sinY) * s;
        wish.y += (iz * -cosY + ix * -sinY) * s;
      }
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

    const target = wish.clone().add(this.boost);
    this.vel.x += (target.x - this.vel.x) * Math.min(1, dt * ACCEL);
    this.vel.y += (target.y - this.vel.y) * Math.min(1, dt * ACCEL);
    const boostDecay = Math.exp(-BOOST_DECAY * dt);
    this.boost.multiplyScalar(boostDecay);
    if (this.boost.lengthSq() < 1e-4) this.boost.set(0, 0);

    // ---- integrate the player body + slide against the collision world ----
    const bx = this.pos.x, bz = this.pos.z;
    this.pos.x += this.vel.x * dt;
    this.pos.z += this.vel.y * dt;
    let bump = null;
    if (this.world) {
      bump = this.world.resolve(this.pos, this.vel);
      if (this.walkTarget && bump && (bump.ob || bump.impact > 0.7)) this.walkTarget = null;
    }
    const movedDist = Math.hypot(this.pos.x - bx, this.pos.z - bz);
    const spd = this.vel.length();

    // ---- metres travelled → footsteps + bob ----
    this.travelled += movedDist;
    const dSp = Math.hypot(this.pos.x - this.start.x, this.pos.z - this.start.z);
    if (dSp > this.maxDisp) this.maxDisp = dSp;
    this._stepAccum += movedDist;
    if (this._stepAccum >= STEP_LEN) {
      this._stepAccum -= STEP_LEN;
      this.onStep && this.onStep(this.stepMaterial);
    }
    this.bobPhase += movedDist * (Math.PI / STEP_LEN);
    const bob = BOB_AMP * Math.sin(this.bobPhase) * Math.min(1, spd / 1.1);

    // ---- apply: the camera REALLY moves with the body (6DoF) ----
    cam.position.set(this.pos.x, EYE_HEIGHT + bob, this.pos.z);
    const off = this.cameraOffset();
    if (off > this.maxOffsetSeen) this.maxOffsetSeen = off;
    cam.rotation.order = "YXZ";
    cam.rotation.set(this.pitch, this.yaw, 0);

    if (bump && this.onBump) this.onBump(bump);
    return bump;
  }

  /* ------------------------------------------------------------ events */

  _bind() {
    const dom = this.dom;

    this._onKeyDown = (e) => {
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"].includes(e.code)) e.preventDefault();
      this.keys.add(e.code);
      if (this.photo && ["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown"].includes(e.code)) this._fireIntent();
    };
    this._onKeyUp = (e) => this.keys.delete(e.code);
    this._onBlur = () => this.keys.clear();

    this._onPointerDown = (e) => {
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (this._pointers.size === 2) {
        this._down = null;                     // two-finger = walk, not look
        if (this.photo) this._fireIntent();
        return;
      }
      if (!this.enabled) return;
      this._down = { x: e.clientX, y: e.clientY, t: performance.now(), moved: 0, id: e.pointerId };
      try { dom.setPointerCapture(e.pointerId); } catch (err) {}
    };

    this._onPointerMove = (e) => {
      const prev = this._pointers.get(e.pointerId);
      if (this._pointers.size === 2 && prev) {
        const dy = e.clientY - prev.y;
        if (this.enabled && Math.abs(dy) > 0.5) {
          if (this.photo) this._fireIntent();
          else {
            const sinY = Math.sin(this.yaw), cosY = Math.cos(this.yaw);
            this._addBoost(-sinY * -dy * 0.011, -cosY * -dy * 0.011);
          }
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
      if (this.photo) { this._fireIntent(); return; }
      const step = e.deltaMode === 1 ? e.deltaY * 18 : e.deltaY;
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
