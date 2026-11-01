/**
 * PANODROME — Smart Portals v2 (Phase 2.5)
 *
 * Sleek, non-intrusive Matterport/VisionOS-style waypoints:
 *   · a small floating glass pill (billboard sprite, breathing pulse)
 *   · a soft floor target ring under the doorway
 *   · room preview card appears on hover (desktop) / single tap (mobile);
 *     the card's button — or a double-tap on the waypoint — transitions.
 *   · `"sponsored": true` renders a luxury gold accent (brand showroom).
 *
 * Placement is anchored by ray-casting the room's displaced mesh from the
 * pano camera toward `portal.fraction` — so the waypoint hugs the REAL
 * doorway geometry instead of a synthetic box.
 */
import * as THREE from "three";
import { i18n } from "./i18n.js";

const CYAN = "#6ee7ff";
const VIOLET = "#a78bfa";
const GOLD = "#f2c14e";
const GOLD_2 = "#e8a23d";

function markerTexture(colorA, colorB) {
  const s = 160;
  const cv = document.createElement("canvas");
  cv.width = s; cv.height = s;
  const ctx = cv.getContext("2d");
  const c = s / 2;
  // outer glass halo
  let g = ctx.createRadialGradient(c, c, s * 0.05, c, c, s * 0.5);
  g.addColorStop(0, hexA(colorA, 0.30));
  g.addColorStop(0.55, hexA(colorB, 0.12));
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
  // glass ring
  ctx.strokeStyle = "rgba(255,255,255,0.92)";
  ctx.lineWidth = 7;
  ctx.beginPath(); ctx.arc(c, c, s * 0.265, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeStyle = hexA(colorA, 0.65);
  ctx.lineWidth = 3;
  ctx.beginPath(); ctx.arc(c, c, s * 0.335, 0, Math.PI * 2); ctx.stroke();
  // core gradient dot
  g = ctx.createLinearGradient(c - s * 0.1, c - s * 0.1, c + s * 0.1, c + s * 0.1);
  g.addColorStop(0, colorA);
  g.addColorStop(1, colorB);
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(c, c, s * 0.16, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,0.95)";
  ctx.beginPath(); ctx.arc(c, c, s * 0.055, 0, Math.PI * 2); ctx.fill();
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function ringTexture(colorA, colorB) {
  const s = 256;
  const cv = document.createElement("canvas");
  cv.width = s; cv.height = s;
  const ctx = cv.getContext("2d");
  const c = s / 2;
  const g = ctx.createLinearGradient(0, 0, s, s);
  g.addColorStop(0, colorA);
  g.addColorStop(1, colorB);
  ctx.strokeStyle = g;
  ctx.lineWidth = 10;
  ctx.beginPath(); ctx.arc(c, c, s * 0.40, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeStyle = hexA("#ffffff", 0.5);
  ctx.lineWidth = 3;
  ctx.beginPath(); ctx.arc(c, c, s * 0.31, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeStyle = hexA(colorA, 0.22);
  ctx.lineWidth = 26;
  ctx.beginPath(); ctx.arc(c, c, s * 0.44, 0, Math.PI * 2); ctx.stroke();
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function hexA(hex, a) {
  const h = hex.replace("#", "");
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
}

export class Portal {
  /**
   * @param {object} def        portal definition from rooms_db.json
   * @param {THREE.Camera} cam  the pano camera (for distance-adaptive scale)
   */
  constructor(def, cam) {
    this.def = def;
    this.camera = cam;
    this.sponsored = !!def.sponsored;
    this.target = null;
    this.reason = null;
    this.hovered = false;

    const a = this.sponsored ? GOLD : CYAN;
    const b = this.sponsored ? GOLD_2 : VIOLET;

    this.group = new THREE.Group();          // anchor: doorway centre on the mesh
    this.group.position.fromArray(def.position);

    // floating glass pill (billboard sprite)
    this.spriteMat = new THREE.SpriteMaterial({
      map: markerTexture(a, b),
      transparent: true, opacity: 0, depthWrite: false, depthTest: true,
    });
    this.marker = new THREE.Sprite(this.spriteMat);
    this.marker.renderOrder = 7;
    this.marker.position.set(0, 0, 0);
    this.group.add(this.marker);

    // floor target ring (flat on the floor, slightly into the room)
    this.ringMat = new THREE.MeshBasicMaterial({
      map: ringTexture(a, b), transparent: true, opacity: 0,
      depthWrite: false, side: THREE.DoubleSide,
    });
    this.ring = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), this.ringMat);
    this.ring.rotation.x = -Math.PI / 2;
    this.ring.renderOrder = 5;
    this.group.add(this.ring);

    // invisible collider (raycast target; radius scales with distance)
    this.collider = new THREE.Mesh(
      new THREE.SphereGeometry(0.5, 8, 8),
      new THREE.MeshBasicMaterial({ visible: false })
    );
    this.group.add(this.collider);

    this.phase = Math.random() * Math.PI * 2;
    this.baseOpacity = 0;
  }

  /**
   * Snap the waypoint onto the real doorway geometry: ray-cast the room mesh
   * from the PANORAMA SHOOT POINT (room.camera) toward the portal fraction,
   * then pull the marker into the room and drop the ring on the floor beneath.
   * @param {THREE.Object3D} roomMesh
   * @param {{x:number,y:number,z:number}} panoCam  room.camera (ray origin)
   * @param {number} fraction
   * @param {number} [floorY]
   */
  anchorOnMesh(roomMesh, panoCam, fraction, floorY = 0) {
    const phi = 2 * Math.PI * fraction;
    // aim at the door CENTRE height (≈1.3 m), not above the transom
    const theta = Math.PI / 2 - THREE.MathUtils.degToRad(-8);
    const st = Math.sin(theta);
    const dir = new THREE.Vector3(-Math.cos(phi) * st, Math.cos(theta), Math.sin(phi) * st);
    const origin = new THREE.Vector3(panoCam.x, panoCam.y, panoCam.z);
    const ray = new THREE.Raycaster(origin, dir.clone().normalize(), 0.1, 200);
    const hit = ray.intersectObject(roomMesh, false)[0];
    if (hit) {
      const p = hit.point.clone();
      const toCam = origin.clone().sub(p);
      toCam.y = 0;
      if (toCam.lengthSq() < 1e-6) toCam.set(-dir.x, 0, -dir.z);
      toCam.normalize();
      // marker floats ~0.55 m into the room, at the door-centre height
      const anchor = p.clone().addScaledVector(toCam, 0.55);
      anchor.y = THREE.MathUtils.clamp(p.y, 1.1, 1.9);
      this.group.position.copy(anchor);
      this.ring.position.set(0, floorY + 0.03 - anchor.y, 0);
      this._toCam = toCam;
      this.wallDist = origin.distanceTo(p);
    } else {
      this.group.position.fromArray(this.def.position);
      this.ring.position.set(0, -this.group.position.y + floorY + 0.03, 0);
    }
    const n = this._toCam || new THREE.Vector3().fromArray(this.def.normal).normalize();
    this.normal = n.clone();
  }

  update(t, dt, hovered) {
    this.hovered = !!hovered;
    const camDist = this.camera ? this.camera.position.distanceTo(this.group.position) : 3;
    // keep the pill ~36px on screen (scale with distance), floor ring in metres
    const pillScale = THREE.MathUtils.clamp(camDist * 0.052, 0.16, 1.15);
    const pulse = 1 + 0.1 * Math.sin(t * 2.2 + this.phase);
    this.marker.scale.setScalar(pillScale * pulse * (this.hovered ? 1.25 : 1));

    const ringBase = THREE.MathUtils.clamp(camDist * 0.2, 0.75, 2.8);
    const rPulse = 1 + 0.05 * Math.sin(t * 1.6 + this.phase);
    this.ring.scale.setScalar(ringBase * rPulse);
    this.ring.rotation.z = t * 0.22;

    this.collider.scale.setScalar(
      THREE.MathUtils.clamp(camDist * 0.16, 0.8, 3.2)
    );

    const target = this.hovered ? 1 : 0.82;
    this.baseOpacity += (target - this.baseOpacity) * Math.min(1, dt * 6);
    this.spriteMat.opacity = this.baseOpacity * (0.85 + 0.15 * Math.sin(t * 2.6 + this.phase));
    this.ringMat.opacity = Math.min(1, this.baseOpacity * 0.95);
  }

  /** Proximity trigger — walking into the doorway. */
  contains(camPos) {
    const d = this.group.position.distanceTo(camPos);
    return d < 1.15 && Math.abs(camPos.y - this.group.position.y) < 1.6;
  }

  colliderMeshes() {
    return [this.collider];
  }

  dispose() {
    this.group.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) {
        if (o.material.map) o.material.map.dispose();
        o.material.dispose();
      }
    });
  }
}

/* ================================================================== *
 * Portal preview card — hover (desktop) / tap (mobile) → card;
 * card button or double-tap → transition. Mobile renders as a bottom
 * sheet (CSS class .sheet handles the layout switch).
 * ================================================================== */
export class PortalCard {
  constructor(onEnter) {
    this.onEnter = onEnter;
    this.portal = null;
    this.el = {
      card: document.getElementById("portal-card"),
      img: document.getElementById("portal-img"),
      chip: document.getElementById("portal-chip"),
      sponsored: document.getElementById("portal-sponsored"),
      name: document.getElementById("portal-name"),
      meta: document.getElementById("portal-meta"),
      enter: document.getElementById("portal-enter"),
      close: document.getElementById("portal-close"),
    };
    this.el.enter.addEventListener("click", () => this._enter());
    this.el.close.addEventListener("click", () => this.hide());
    this._onDocDown = (e) => {
      if (!this.portal) return;
      if (this.el.card.contains(e.target)) return;
      this.hide();
    };
    document.addEventListener("pointerdown", this._onDocDown, true);
    i18n.onChange(() => this.portal && this.fill(this.portal, this.targetRoom));
  }

  get open() { return !!this.portal; }

  show(portal, targetRoom) {
    this.portal = portal;
    this.targetRoom = targetRoom;
    this.fill(portal, targetRoom);
    this.el.card.classList.add("open");
  }

  hide() {
    this.portal = null;
    this.el.card.classList.remove("open");
  }

  _enter() {
    const p = this.portal;
    if (!p) return;
    this.hide();
    this.onEnter(p);
  }

  fill(portal, room) {
    if (!room) return;
    const t = i18n.t, L = i18n.lang;
    this.el.img.src = room.preview;
    this.el.img.alt = room.name[L] || room.name.en;
    this.el.chip.textContent = t.portal_label;
    this.el.name.textContent = room.name[L] || room.name.en;
    const type = t["type_" + room.room_type] || room.room_type;
    const reason = t.reason[portal.reason] || "";
    this.el.meta.innerHTML = `${type} · ${t.portal_to} <b>${room.name[L] || room.name.en}</b>${reason ? ` · ${reason}` : ""}`;
    this.el.sponsored.classList.toggle("hud-hidden", !portal.sponsored);
    this.el.sponsored.textContent = t.sponsored_badge;
    this.el.enter.textContent = t.portal_enter;
  }
}

// ---------------------------------------------------------------- routing

export function computeRoutes(rooms, currentIndex, mode) {
  const n = rooms.length;
  const cur = rooms[currentIndex];
  const pick = (arr) => {
    const others = arr.filter((i) => i !== currentIndex);
    if (!others.length) return [(currentIndex + 1) % n, (currentIndex + 2) % n];
    return others;
  };

  if (mode === "architect") {
    return { targets: [(currentIndex + 1) % n, (currentIndex + 2) % n], reason: "architect" };
  }

  if (mode === "room_type") {
    const same = [];
    for (let i = 0; i < n; i++) if (rooms[i].room_type === cur.room_type) same.push(i);
    const list = pick(same);
    return { targets: [list[0], list[1] !== undefined ? list[1] : (currentIndex + 1) % n], reason: "room_type" };
  }

  if (mode === "style") {
    const scored = [];
    for (let i = 0; i < n; i++) {
      if (i === currentIndex) continue;
      const overlap = rooms[i].style_tags.filter((tg) => cur.style_tags.includes(tg)).length;
      scored.push([overlap, i]);
    }
    scored.sort((a, b) => b[0] - a[0] || a[1] - b[1]);
    const strong = scored.filter((s) => s[0] > 0);
    const list = strong.length ? strong : scored;
    return {
      targets: [list[0][1], list[1] ? list[1][1] : (currentIndex + 1) % n],
      reason: "style",
    };
  }

  // random serendipity
  const pool = [...Array(n).keys()].filter((i) => i !== currentIndex);
  const a = pool.splice(Math.floor(Math.random() * pool.length), 1)[0];
  const b = pool.length ? pool[Math.floor(Math.random() * pool.length)] : (currentIndex + 1) % n;
  return { targets: [a, b], reason: "random" };
}

/**
 * Dream House tour routing (Phase 2 moodboard): portals follow the curated
 * chain exclusively — portal 1 steps to the next room in the sequence,
 * portal 2 steps back. Unknown ids are dropped; returns null for empty chains.
 */
export function computeHouseRoutes(rooms, currentIndex, chainIds) {
  const idxOf = (id) => rooms.findIndex((r) => r.id === id);
  const chain = chainIds.map(idxOf).filter((i) => i >= 0);
  const n = chain.length;
  if (!n) return null;
  if (n === 1) return { targets: [chain[0], chain[0]], reason: "house" };
  const pos = chain.indexOf(currentIndex);
  if (pos === -1) return { targets: [chain[0], chain[1]], reason: "house" };
  return {
    targets: [chain[(pos + 1) % n], chain[(pos - 1 + n) % n]],
    reason: "house",
  };
}
