/**
 * PANODROME — Stage 2.1 · 3D Dollhouse / Roof-Off Orbit (owner order
 * 2026-11-03 — "نمای ماکت و برداشتن سقف", inspired by scale_immersive's
 * "Now you are taking the roof off!" and Claude's Orbit mode).
 *
 * One tap on the HUD 🏠 button:
 *   · the ceiling smoothly LIFTS + fades away (roof-off),
 *   · the camera rises into an interactive orbit above the room,
 *   · the radar grows into the 2D floor-plan dimension view (m),
 *   · tapping any floor point glides the player DOWN into first-person
 *     Walk mode at that exact spot.
 */
import * as THREE from "three";

const LIFT_FACTOR = 0.62;     // ceiling lift = room height * factor
const FADE_MS = 0.55;

export class Dollhouse {
  /**
   * @param camera
   * @param {object} cbs { onTapFloor(x,z), onOrbit?() }
   */
  constructor(camera, dom, cbs) {
    this.camera = camera;
    this.dom = dom;
    this.cbs = cbs;
    this.active = false;
    this.ceilings = [];          // [{mesh, y0, mats: [{m, transparent0}]}]
    this.az = 0.8;
    this.pol = 0.9;              // polar from vertical (rad)
    this.radius = 8;
    this.center = new THREE.Vector3();
    this.minR = 2.5;
    this.maxR = 30;
    this._down = null;
    this._raf = null;
    this._saved = null;
  }

  /** Collect ceiling meshes from the loaded room composite. */
  _collectCeilings(meshObj) {
    this.ceilings = [];
    if (!meshObj || !meshObj.mesh) return;
    meshObj.mesh.traverse((o) => {
      const n = o.name || "";
      if (o.isMesh && (n.startsWith("ceiling") || n.startsWith("roof"))) {
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        this.ceilings.push({
          mesh: o,
          y0: o.position.y,
          mats: mats.map((m) => ({ m, t0: m.transparent, o0: m.opacity })),
        });
      }
    });
  }

  _applyLift(k) {
    this._liftNow = k;
    const lift = (this._roomH || 3) * LIFT_FACTOR;
    for (const c of this.ceilings) {
      c.mesh.position.y = c.y0 + lift * k;
      for (const e of c.mats) {
        e.m.transparent = true;
        e.m.opacity = e.o0 * (1 - k);
      }
    }
  }

  /** Enter dollhouse: lift the roof, tween the camera up, start orbiting. */
  enter(meshObj, room, renderer, currentCamPos) {
    if (this.active) return;
    this.active = true;
    if (this._exitTween) { this._exitTween.kill(); this._exitTween = null; }
    this._roomH = room.room_shape.height;
    const W = room.room_shape.width, D = room.room_shape.depth;
    this._collectCeilings(meshObj);
    this.center.set(0, Math.min(this._roomH * 0.4, 2.2), 0);
    this.radius = THREE.MathUtils.clamp(Math.max(W, D) * 0.72, 3.5, 26);
    this.minR = this.radius * 0.45;
    this.maxR = this.radius * 1.6;

    const from = this.camera.position.clone();
    const fromQ = this.camera.quaternion.clone();
    // start the orbit from the player's current azimuth for continuity
    this.az = Math.atan2(from.x, from.z);
    const target = this._orbitPos(0.9);
    const self = this;
    const qWork = new THREE.Quaternion();

    this._enterTween = gsap.to({ t: 0 }, {
      t: 1, duration: 1.05, ease: "power2.inOut",
      onUpdate() {
        const t = this.targets()[0].t;
        self.camera.position.lerpVectors(from, target, t);
        const look = new THREE.Matrix4().lookAt(self.camera.position, self.center, new THREE.Vector3(0, 1, 0));
        qWork.setFromRotationMatrix(look);
        self.camera.quaternion.copy(fromQ).slerp(qWork, t);
        self._applyLift(t);
      },
      onComplete() {
        self._enterTween = null;
        if (!self.active) return;                 // exited mid-flight
        self.camera.quaternion.setFromRotationMatrix(
          new THREE.Matrix4().lookAt(self.camera.position, self.center, new THREE.Vector3(0, 1, 0)));
        self._bind();
        self.cbs.onReady && self.cbs.onReady();
      },
    });
  }

  _orbitPos(pol) {
    const p = THREE.MathUtils.clamp(pol, 0.18, 1.32);
    return new THREE.Vector3(
      this.center.x + this.radius * Math.sin(p) * Math.sin(this.az),
      this.center.y + this.radius * Math.cos(p),
      this.center.z + this.radius * Math.sin(p) * Math.cos(this.az),
    );
  }

  _updateCam() {
    this.camera.position.copy(this._orbitPos(this.pol));
    this.camera.lookAt(this.center);
  }

  /** Smooth descent to a floor point, then hand back to Walk mode. */
  exitTo(x, z, onDone) {
    if (!this.active) return;
    this.active = false;
    if (this._enterTween) { this._enterTween.kill(); this._enterTween = null; }
    this._unbind();
    const from = this.camera.position.clone();
    const fromQ = this.camera.quaternion.clone();
    const liftFrom = this._liftNow || 1;
    const to = new THREE.Vector3(x, 1.65, z);
    const self = this;
    const yaw = this._exitYaw || 0;
    const qWork = new THREE.Quaternion();
    this._exitTween = gsap.to({ t: 0 }, {
      t: 1, duration: 1.15, ease: "power2.inOut",
      onUpdate() {
        const t = this.targets()[0].t;
        self.camera.position.lerpVectors(from, to, t);
        const look = new THREE.Matrix4().lookAt(self.camera.position,
          new THREE.Vector3(x - Math.sin(yaw) * 4, 1.55, z - Math.cos(yaw) * 4),
          new THREE.Vector3(0, 1, 0));
        qWork.setFromRotationMatrix(look);
        self.camera.quaternion.copy(fromQ).slerp(qWork, t);
        self._applyLift(liftFrom * (1 - t));
        self._liftNow = liftFrom * (1 - t);
      },
      onComplete() {
        self._exitTween = null;
        for (const c of self.ceilings) {
          c.mesh.position.y = c.y0;
          for (const e of c.mats) { e.m.transparent = e.t0; e.m.opacity = e.o0; }
        }
        self.ceilings = [];
        self._liftNow = 0;
        onDone && onDone(x, z, self._exitYaw || 0);
      },
    });
  }

  /** Instant exit (HUD toggle) — restore roof, don't move the player. */
  exitQuick() {
    if (!this.active && !this._enterTween) return;
    this.active = false;
    if (this._enterTween) { this._enterTween.kill(); this._enterTween = null; }
    if (this._exitTween) { this._exitTween.kill(); this._exitTween = null; }
    this._unbind();
    for (const c of this.ceilings) {
      c.mesh.position.y = c.y0;
      for (const e of c.mats) { e.m.transparent = e.t0; e.m.opacity = e.o0; }
    }
    this.ceilings = [];
    this._liftNow = 0;
  }

  /* --------------------------------------------------------- orbit input */
  _bind() {
    const dom = this.dom;
    this._onDown = (e) => {
      this._down = { x: e.clientX, y: e.clientY, t: performance.now(), moved: 0, id: e.pointerId };
      try { dom.setPointerCapture(e.pointerId); } catch (err) {}
    };
    this._onMove = (e) => {
      if (!this._down || e.pointerId !== this._down.id) return;
      const dx = e.clientX - this._down.x, dy = e.clientY - this._down.y;
      this._down.x = e.clientX; this._down.y = e.clientY;
      this._down.moved += Math.abs(dx) + Math.abs(dy);
      this.az -= dx * 0.005;
      this.pol = THREE.MathUtils.clamp(this.pol + dy * 0.004, 0.2, 1.3);
      this._updateCam();
    };
    this._onUp = (e) => {
      if (!this._down || e.pointerId !== this._down.id) return;
      const quick = performance.now() - this._down.t < 350 && this._down.moved < 8;
      const { x, y } = this._down;
      this._down = null;
      if (quick) this.cbs.onTapFloor && this.cbs.onTapFloor(x, y);
    };
    this._onWheel = (e) => {
      e.preventDefault();
      const k = Math.exp(e.deltaY * 0.0012);
      this.radius = THREE.MathUtils.clamp(this.radius * k, this.minR, this.maxR);
      this._updateCam();
    };
    dom.addEventListener("pointerdown", this._onDown);
    dom.addEventListener("pointermove", this._onMove);
    dom.addEventListener("pointerup", this._onUp);
    dom.addEventListener("pointercancel", this._onUp);
    dom.addEventListener("wheel", this._onWheel, { passive: false });
  }

  _unbind() {
    const dom = this.dom;
    if (this._onDown) {
      dom.removeEventListener("pointerdown", this._onDown);
      dom.removeEventListener("pointermove", this._onMove);
      dom.removeEventListener("pointerup", this._onUp);
      dom.removeEventListener("pointercancel", this._onUp);
      dom.removeEventListener("wheel", this._onWheel);
      this._onDown = null;
    }
  }
}
