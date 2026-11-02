/**
 * PANODROME — Stage 1.5 · Walk World (physics collision + floor walk FX)
 *
 * Game-engine walking physics for the true room volume:
 *   · room_bounds  — the walkable perimeter: the room box inset by 0.6 m so
 *     the camera never clips a wall and never gets close enough for texture
 *     stretching.
 *   · obstacle_colliders — metric boxes / cylinders at the real world
 *     coordinates of furniture (sofa groups, grand piano, café tables, stage,
 *     stoves, easels…) from rooms_db.json.
 *   · SLIDING response — forward penetration is blocked, tangential motion
 *     continues: you glide along the obstacle tangent exactly like a real
 *     3D game engine. Direct bumps surface as events (HUD ripple + toast +
 *     soft thud).
 *
 * Walk FX (subtle, invisible-luxury):
 *   · floor footpath grid (y = 0.02) that fades in only while walking —
 *     the 3D floor plane visibly sliding underneath your feet
 *   · a soft walkable-zone ring that follows the player
 */
import * as THREE from "three";

const BUMP_SPEED = 0.35;     // m/s along the normal to count as a real bump
const BUMP_PUSH = 0.004;     // m of push-out per frame to count as contact

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
      hw: (o.hw ?? o.r) , hd: (o.hd ?? o.r),
      label: o.label || { en: "Obstacle", fa: "مانع" },
    }));
  }

  /**
   * Resolve one integration step with sliding collision.
   * @param {THREE.Vector3} pos    player position (mutated in place)
   * @param {THREE.Vector2} vel    player velocity (m/s, mutated: inward
   *                               normal components are cancelled → slide)
   * @returns {null | {label:{en,fa}, nx:number, nz:number, impact:number}}
   */
  resolve(pos, vel) {
    let bump = null;
    const R = this.playerR;

    // ---- walls: axis-separated clamp = classic tangent slide ----
    if (pos.x < this.bounds.minX) {
      if (vel.x < -BUMP_SPEED && this.bounds.minX - pos.x > BUMP_PUSH) bump = wallBump(vel, 1, 0);
      pos.x = this.bounds.minX;
      if (vel.x < 0) vel.x = 0;
    } else if (pos.x > this.bounds.maxX) {
      if (vel.x > BUMP_SPEED && pos.x - this.bounds.maxX > BUMP_PUSH) bump = wallBump(vel, -1, 0);
      pos.x = this.bounds.maxX;
      if (vel.x > 0) vel.x = 0;
    }
    if (pos.z < this.bounds.minZ) {
      if (vel.y < -BUMP_SPEED && this.bounds.minZ - pos.z > BUMP_PUSH) bump = bump || wallBump(vel, 0, 1);
      pos.z = this.bounds.minZ;
      if (vel.y < 0) vel.y = 0;
    } else if (pos.z > this.bounds.maxZ) {
      if (vel.y > BUMP_SPEED && pos.z - this.bounds.maxZ > BUMP_PUSH) bump = bump || wallBump(vel, 0, -1);
      pos.z = this.bounds.maxZ;
      if (vel.y > 0) vel.y = 0;
    }

    // ---- obstacles: circle-vs-box / circle-vs-circle push-out ----
    for (const o of this.obstacles) {
      let nx, nz, push;
      if (o.type === "cyl") {
        const ddx = pos.x - o.x, ddz = pos.z - o.z;
        const d = Math.hypot(ddx, ddz);
        const rr = o.hw + R;                    // o.hw = o.hd = radius
        if (d >= rr) continue;
        if (d < 1e-6) { nx = 1; nz = 0; }
        else { nx = ddx / d; nz = ddz / d; }    // away from the axis — correct even when inside
        push = rr - d;
      } else {
        const cx = THREE.MathUtils.clamp(pos.x, o.x - o.hw, o.x + o.hw);
        const cz = THREE.MathUtils.clamp(pos.z, o.z - o.hd, o.z + o.hd);
        const dx = pos.x - cx, dz = pos.z - cz;
        const d = Math.hypot(dx, dz);
        if (d >= R) continue;
        if (d < 1e-6) {
          // centre inside the box: push out along the shallowest axis
          const px = (o.hw + R) - Math.abs(pos.x - o.x);
          const pz = (o.hd + R) - Math.abs(pos.z - o.z);
          if (px < pz) { nx = Math.sign(pos.x - o.x) || 1; nz = 0; push = px; }
          else { nx = 0; nz = Math.sign(pos.z - o.z) || 1; push = pz; }
        } else {
          nx = dx / d; nz = dz / d; push = R - d;
        }
      }
      pos.x += nx * push;
      pos.z += nz * push;
      // cancel the inward normal velocity → slide along the tangent
      const vn = vel.x * nx + vel.y * nz;
      if (vn < 0) {
        if (vn < -BUMP_SPEED && push > BUMP_PUSH) {
          bump = { label: o.label, nx, nz, impact: -vn };
        }
        vel.x -= vn * nx;
        vel.y -= vn * nz;
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
  return { label: { en: "Wall", fa: "دیوار" }, nx, nz, impact: Math.hypot(vel.x, vel.y) };
}

/* ============================================================ walk FX */

const GRID_COLOR = 0x9fc6ec;

/** Floor footpath grid + player ring; opacity fades in only while moving. */
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
  }

  dispose(scene) {
    scene.remove(this.grid);
    scene.remove(this.ring);
    this.grid.geometry.dispose();
    this.grid.material.dispose();
    this.ring.geometry.dispose();
    this.ring.material.dispose();
  }
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
