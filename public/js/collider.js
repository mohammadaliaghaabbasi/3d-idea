/**
 * PANODROME — Stage 1.6.1 · Walk World (physics + glass floor halos)
 * ============================================================================
 * Game-engine walking physics for the relief-dome rooms (owner order
 * 2026-11-02 — Rule C: furniture collision stays REAL):
 *   · room_bounds  — the walkable perimeter (authored box inset 0.6 m):
 *     an outer safety clamp; the primary boundary is the elastic radial
 *     walk envelope (controls.js).
 *   · obstacle_colliders — metric boxes (optionally YAWED — OBB) / cylinders
 *     at the real world coordinates of furniture (sofa groups, grand
 *     piano, café tables, cabin bed, stoves…).  Sliding response with
 *     tangent glide; direct bumps surface as events (HUD toast + ripple +
 *     soft thud + halo flash).
 *   · OBSTACLE HALOS — a sleek, subtle GLASS BOUNDING CONTOUR + soft floor
 *     exclusion fill around every obstacle: proximity-faded, breathing
 *     softly, flashing on impact.  The player SEES the collider boundary
 *     before feeling it — no invisible walls, ever.
 */
import * as THREE from "three";

// Bump events fire on CONTACT TRANSITIONS (Stage 1.6.1): entering contact
// with a body surfaces the event once — deliberate slow auto-walk touches
// and fast human strides behave identically.  0.9 s per-body cooldown.
const BUMP_COOLDOWN_MS = 900;

export class WalkWorld {
  /** @param {object} room  rooms_db.json room record (walk.bounds + obstacles) */
  constructor(room) {
    this.room = room;
    const b = room.walk.bounds;
    this.bounds = { minX: b.minX, maxX: b.maxX, minZ: b.minZ, maxZ: b.maxZ };
    this.playerR = room.walk.player_radius ?? 0.3;
    this.obstacles = (room.walk.obstacles || []).map((o) => ({
      type: o.type === "box" ? "box" : "cyl",
      x: o.x, z: o.z,
      hw: (o.hw ?? o.r), hd: (o.hd ?? o.r),
      rot: o.rot || 0,                       // OBB yaw (radians, optional)
      label: o.label || { en: "Obstacle", fa: "مانع" },
      raw: o,
    }));
    this._bumpAt = new Map();                // obstacle/wall key -> last event ms
    this._contact = new Set();              // obstacles currently touching
    this._wallTouch = new Set();            // wall sides currently touching
  }

  /**
   * Resolve one integration step with sliding collision.
   * Bump events fire on CONTACT TRANSITIONS (not touching -> touching), so a
   * deliberate slow auto-walk into an obstacle surfaces exactly like a fast
   * human stride — one event per contact episode, 0.9 s cooldown per body.
   * @returns {null | {label:{en,fa}, nx:number, nz:number, impact:number, ob:object}}
   */
  resolve(pos, vel) {
    let bump = null;
    const R = this.playerR;
    const now = performance.now();
    const fire = (key, b) => {
      const last = this._bumpAt.get(key) || 0;
      if (now - last < BUMP_COOLDOWN_MS) return null;
      this._bumpAt.set(key, now);
      return b;
    };

    // ---- walls: axis-separated clamp = classic tangent slide ----
    const wallN = { "x-": [1, 0], "x+": [-1, 0], "z-": [0, 1], "z+": [0, -1] };
    const wallTouch = new Set();
    if (pos.x < this.bounds.minX) { wallTouch.add("x-"); pos.x = this.bounds.minX; if (vel.x < 0) vel.x = 0; }
    else if (pos.x > this.bounds.maxX) { wallTouch.add("x+"); pos.x = this.bounds.maxX; if (vel.x > 0) vel.x = 0; }
    if (pos.z < this.bounds.minZ) { wallTouch.add("z-"); pos.z = this.bounds.minZ; if (vel.y < 0) vel.y = 0; }
    else if (pos.z > this.bounds.maxZ) { wallTouch.add("z+"); pos.z = this.bounds.maxZ; if (vel.y > 0) vel.y = 0; }
    for (const k of wallTouch) {
      if (!this._wallTouch.has(k)) {
        const [nx, nz] = wallN[k];
        bump = bump || fire("wall" + k, {
          label: { en: "Wall", fa: "دیوار" }, nx, nz,
          impact: Math.max(Math.hypot(vel.x, vel.y), 0.25), ob: null,
        });
      }
    }
    this._wallTouch = wallTouch;

    // ---- obstacles: circle-vs-OBB / circle-vs-circle push-out ----
    for (const o of this.obstacles) {
      let nx, nz, push, touching;
      if (o.type === "cyl") {
        const ddx = pos.x - o.x, ddz = pos.z - o.z;
        const d = Math.hypot(ddx, ddz);
        const rr = o.hw + R;                    // o.hw = o.hd = radius
        touching = d < rr;
        if (!touching) { this._contact.delete(o); continue; }
        if (d < 1e-6) { nx = 1; nz = 0; }
        else { nx = ddx / d; nz = ddz / d; }
        push = rr - d;
      } else {
        // player position in the box LOCAL frame (yaw support)
        const cr = Math.cos(-o.rot), sr = Math.sin(-o.rot);
        const rx = pos.x - o.x, rz = pos.z - o.z;
        const lx = cr * rx - sr * rz;
        const lz = sr * rx + cr * rz;
        const cx = THREE.MathUtils.clamp(lx, -o.hw, o.hw);
        const cz = THREE.MathUtils.clamp(lz, -o.hd, o.hd);
        const dx = lx - cx, dz = lz - cz;
        const d = Math.hypot(dx, dz);
        touching = d < R;
        if (!touching) { this._contact.delete(o); continue; }
        let lnx, lnz;
        if (d < 1e-6) {
          const px = (o.hw + R) - Math.abs(lx);
          const pz = (o.hd + R) - Math.abs(lz);
          if (px < pz) { lnx = Math.sign(lx) || 1; lnz = 0; push = px; }
          else { lnx = 0; lnz = Math.sign(lz) || 1; push = pz; }
        } else {
          lnx = dx / d; lnz = dz / d; push = R - d;
        }
        // local normal -> world (rotate by +rot)
        const cw = Math.cos(o.rot), sw = Math.sin(o.rot);
        nx = cw * lnx - sw * lnz;
        nz = sw * lnx + cw * lnz;
      }
      const isNew = !this._contact.has(o);
      this._contact.add(o);
      pos.x += nx * push;
      pos.z += nz * push;
      // cancel the inward normal velocity → slide along the tangent
      const vn = vel.x * nx + vel.y * nz;
      if (vn < 0) {
        vel.x -= vn * nx;
        vel.y -= vn * nz;
      }
      if (isNew) {
        bump = bump || fire(o, {
          label: o.label, nx, nz,
          impact: Math.max(-vn, 0.25), ob: o,
        });
      }
    }
    return bump;
  }

  /** True if a world point is inside the walkable area (E2E helper). */
  insideWalkable(x, z, pad = 0) {
    return x >= this.bounds.minX - pad && x <= this.bounds.maxX + pad &&
           z >= this.bounds.minZ - pad && z <= this.bounds.maxZ + pad;
  }
}

function wallBump(vel, nx, nz) {
  return { label: { en: "Wall", fa: "دیوار" }, nx, nz, impact: Math.hypot(vel.x, vel.y), ob: null };
}

/* ============================================================ walk FX */

const GRID_COLOR = 0x9fc6ec;
const HALO_LINE_COLOR = 0xeaf5ff;
const HALO_FILL_COLOR = 0xaacfe8;

/** Floor footpath grid + player ring + obstacle halos. */
export class WalkFX {
  constructor(scene, room) {
    const { width, depth } = room.room_shape;
    const cell = Math.max(width, depth) > 15 ? 1.0 : 0.5;
    this.grid = buildGrid(width, depth, cell);
    this.grid.position.y = 0.02;
    scene.add(this.grid);

    this.ring = new THREE.Mesh(
      new THREE.RingGeometry(0.5, 0.55, 48),
      new THREE.MeshBasicMaterial({
        color: 0xcfe4ff, transparent: true, opacity: 0,
        side: THREE.DoubleSide, depthWrite: false,
      })
    );
    this.ring.rotation.x = -Math.PI / 2;
    this.ring.position.y = 0.021;
    scene.add(this.ring);

    this.halos = new ObstacleHalos(scene, room.walk.obstacles || []);

    this._gridOpacity = 0;
    this._ringOpacity = 0;
    this._pulse = 0;
  }

  /** @param {THREE.Vector3} pos  player position  · moving {boolean} */
  update(dt, pos, speed) {
    const moving = speed > 0.15;
    this._pulse += dt * 1.6;

    const gTarget = moving ? 0.13 : 0;
    const rTarget = moving ? 0.30 + 0.08 * Math.sin(this._pulse * Math.PI) : 0;
    this._gridOpacity += (gTarget - this._gridOpacity) * Math.min(1, dt * 3.2);
    this._ringOpacity += (rTarget - this._ringOpacity) * Math.min(1, dt * 3.2);
    this.grid.material.opacity = this._gridOpacity;
    this.grid.material.transparent = true;
    this.ring.material.opacity = this._ringOpacity;

    this.ring.position.x = pos.x;
    this.ring.position.z = pos.z;
    const s = 1 + Math.min(speed / 2.2, 1) * 0.16 + 0.03 * Math.sin(this._pulse * Math.PI * 2);
    this.ring.scale.setScalar(s);

    this.halos.update(dt, pos);
  }

  dispose(scene) {
    scene.remove(this.grid);
    scene.remove(this.ring);
    this.grid.geometry.dispose();
    this.grid.material.dispose();
    this.ring.geometry.dispose();
    this.ring.material.dispose();
    this.halos.dispose(scene);
  }
}

/* ------------------------------------------------------------ glass halos */

/**
 * Sleek glass bounding contours on the floor around every obstacle
 * (owner spec: "3D Glass Bounding Contour / Floor Exclusion Halo").
 * Subtle constant visibility, proximity-fades in, bump-flashes.
 */
export class ObstacleHalos {
  constructor(scene, obstacles) {
    this.items = [];
    for (const o of obstacles || []) {
      const it = buildHalo(o);
      if (!it) continue;
      scene.add(it.line);
      scene.add(it.fill);
      this.items.push(it);
    }
    this._scene = scene;
  }

  get count() { return this.items.length; }

  update(dt, playerPos) {
    for (const it of this.items) {
      const dx = playerPos.x - it.cx, dz = playerPos.z - it.cz;
      const dist = Math.hypot(dx, dz);
      const gap = Math.max(0, dist - it.effR - 0.3);
      const prox = THREE.MathUtils.clamp(1 - gap / 1.5, 0, 1);
      it.prox += (prox - it.prox) * Math.min(1, dt * 5);
      it.flash = Math.max(0, it.flash - dt * 1.8);
      const breathe = 0.02 * Math.sin(performance.now() * 0.0012 + it.phase);
      it.line.material.opacity = 0.07 + 0.30 * it.prox * it.prox + 0.50 * it.flash + breathe;
      it.fill.material.opacity = 0.022 + 0.09 * it.prox * it.prox + 0.22 * it.flash;
      const s = 1 + 0.045 * it.flash;
      it.line.scale.set(s, 1, s);
      it.fill.scale.set(s, s, 1);
    }
  }

  /** Flash the halo of the obstacle that was just bumped. */
  flash(ob) {
    if (!ob) return;
    const it = this.items.find((i) => i.ob === ob || i.ob === ob.raw);
    if (it) it.flash = 1;
  }

  dispose(scene) {
    const sc = scene || this._scene;
    for (const it of this.items) {
      sc.remove(it.line);
      sc.remove(it.fill);
      it.line.geometry.dispose();
      it.line.material.dispose();
      it.fill.geometry.dispose();
      it.fill.material.dispose();
    }
    this.items = [];
  }
}

function buildHalo(o) {
  const isCyl = o.type !== "box";
  const rot = o.rot || 0;
  let effR, line, fill;
  const yLine = 0.018, yFill = 0.014;

  if (isCyl) {
    const r = (o.r ?? o.hw ?? 0) + 0.025;
    effR = o.r ?? o.hw ?? 0;
    const pts = [];
    for (let i = 0; i <= 72; i++) {
      const a = (i / 72) * Math.PI * 2;
      pts.push(new THREE.Vector3(o.x + r * Math.cos(a), yLine, o.z + r * Math.sin(a)));
    }
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    line = new THREE.LineLoop(geo, new THREE.LineBasicMaterial({
      color: HALO_LINE_COLOR, transparent: true, opacity: 0.07, depthWrite: false,
    }));
    fill = new THREE.Mesh(
      new THREE.CircleGeometry(effR + 0.02, 48),
      new THREE.MeshBasicMaterial({
        color: HALO_FILL_COLOR, transparent: true, opacity: 0.022,
        depthWrite: false, side: THREE.DoubleSide,
      })
    );
    fill.rotation.x = -Math.PI / 2;
    fill.position.set(o.x, yFill, o.z);
  } else {
    const hw = o.hw ?? 0, hd = o.hd ?? 0;
    effR = Math.hypot(hw, hd);
    const cr = Math.min(hw, hd) * 0.35;                 // rounded corners
    const ow = hw + 0.03, od = hd + 0.03;               // outline margin
    // rounded-rect outline (sampled)
    const pts = [];
    const seg = 10;
    const corners = [
      [Math.min(ow - cr, ow), Math.min(od - cr, od), 0],
      [-(ow - cr), od - cr, Math.PI / 2],
      [-ow + 0, -(od - cr), Math.PI],
      [ow - cr, -(od - cr), Math.PI * 1.5],
    ];
    for (const [cx0, cz0, a0] of corners) {
      for (let i = 0; i <= seg; i++) {
        const a = a0 + (i / seg) * (Math.PI / 2);
        const lx = cx0 + cr * Math.cos(a);
        const lz = cz0 + cr * Math.sin(a);
        const cw = Math.cos(rot), sw = Math.sin(rot);
        pts.push(new THREE.Vector3(o.x + cw * lx - sw * lz, yLine, o.z + sw * lx + cw * lz));
      }
    }
    pts.push(pts[0].clone());
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    line = new THREE.LineLoop(geo, new THREE.LineBasicMaterial({
      color: HALO_LINE_COLOR, transparent: true, opacity: 0.07, depthWrite: false,
    }));
    // soft fill (rounded-rect shape)
    const shape = roundedRectShape(hw + 0.01, hd + 0.01, Math.min(hw, hd) * 0.35);
    fill = new THREE.Mesh(
      new THREE.ShapeGeometry(shape, 8),
      new THREE.MeshBasicMaterial({
        color: HALO_FILL_COLOR, transparent: true, opacity: 0.022,
        depthWrite: false, side: THREE.DoubleSide,
      })
    );
    fill.rotation.x = -Math.PI / 2;
    fill.rotation.z = -rot;
    fill.position.set(o.x, yFill, o.z);
  }

  return { line, fill, cx: o.x, cz: o.z, effR, ob: o, prox: 0, flash: 0, phase: Math.random() * Math.PI * 2 };
}

function roundedRectShape(hw, hd, r) {
  const s = new THREE.Shape();
  r = Math.min(r, hw, hd);
  s.moveTo(-hw + r, -hd);
  s.lineTo(hw - r, -hd);
  s.quadraticCurveTo(hw, -hd, hw, -hd + r);
  s.lineTo(hw, hd - r);
  s.quadraticCurveTo(hw, hd, hw - r, hd);
  s.lineTo(-hw + r, hd);
  s.quadraticCurveTo(-hw, hd, -hw, hd - r);
  s.lineTo(-hw, -hd + r);
  s.quadraticCurveTo(-hw, -hd, -hw + r, -hd);
  return s;
}

function buildGrid(w, d, cell) {
  const pts = [];
  const hw = w / 2, hd = d / 2;
  for (let x = -hw; x <= hw + 1e-6; x += cell) {
    pts.push(x, 0, -hd, x, 0, hd);
  }
  for (let z = -hd; z <= hd + 1e-6; z += cell) {
    pts.push(-hw, 0, z, hw, 0, z);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  const mat = new THREE.LineBasicMaterial({
    color: GRID_COLOR, transparent: true, opacity: 0, depthWrite: false,
  });
  return new THREE.LineSegments(geo, mat);
}
