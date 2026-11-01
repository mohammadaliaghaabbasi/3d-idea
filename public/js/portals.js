/**
 * PANODROME — Smart Portals (glowing doorways) + routing modes
 *
 * Each room carries 2 portal definitions in rooms_db.json (position/normal
 * ray-cast onto the room box by the ingest skill; positions come either from
 * the AI vision door pass or curated wall slots).
 *
 * Routing modes decide where each portal leads:
 *   architect — the curated walk (sequential)
 *   room_type — portals lead to rooms of the same type
 *   style     — portals follow shared style/material tags
 *   random    — serendipity
 */
import * as THREE from "three";

const CYAN = new THREE.Color("#6ee7ff");
const VIOLET = new THREE.Color("#a78bfa");

function archShape(w, h) {
  const s = new THREE.Shape();
  const r = w / 2;
  s.moveTo(-r, 0);
  s.lineTo(-r, h - r);
  s.absarc(0, h - r, r, Math.PI, 0, true);
  s.lineTo(r, 0);
  s.closePath();
  return s;
}

const MEMBRANE_VERT = `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const MEMBRANE_FRAG = `
uniform float uTime;
uniform vec3 uColorA;
uniform vec3 uColorB;
varying vec2 vUv;
void main() {
  float d = distance(vUv, vec2(0.5, 0.38));
  float rings = sin(d * 20.0 - uTime * 2.4) * 0.5 + 0.5;
  float pulse = 0.72 + 0.28 * sin(uTime * 1.8);
  float fade = smoothstep(0.0, 0.18, vUv.y);          // soft at the floor
  vec3 col = mix(uColorA, uColorB, clamp(vUv.y, 0.0, 1.0));
  float a = (0.16 + 0.34 * rings) * pulse * fade;
  gl_FragColor = vec4(col, a);
}`;

export class Portal {
  constructor(def) {
    this.def = def;
    this.group = new THREE.Group();
    this.group.position.fromArray(def.position);
    const n = new THREE.Vector3().fromArray(def.normal).normalize();
    this.normal = n;
    this.group.lookAt(this.group.position.clone().add(n));

    const w = def.width, h = def.height;

    // glowing membrane
    this.membraneMat = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uColorA: { value: CYAN.clone() },
        uColorB: { value: VIOLET.clone() },
      },
      vertexShader: MEMBRANE_VERT,
      fragmentShader: MEMBRANE_FRAG,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
    });
    const membrane = new THREE.Mesh(new THREE.ShapeGeometry(archShape(w, h), 24), this.membraneMat);
    // def.position.y (1.07) is the arch CENTRE; the arch shape is built from its base,
    // so drop it by h/2 to put the base on the floor.
    membrane.position.set(0, -h / 2 - 0.02, 0.05);
    this.group.add(membrane);

    // bright rim
    const rim = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.ShapeGeometry(archShape(w, h), 24), 25),
      new THREE.LineBasicMaterial({ color: CYAN, transparent: true, opacity: 0.95 })
    );
    rim.position.copy(membrane.position);
    rim.position.z += 0.01;
    this.rim = rim;
    this.group.add(rim);

    // outer halo plane
    const haloTex = makeHaloTexture();
    this.haloMat = new THREE.MeshBasicMaterial({
      map: haloTex, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    });
    const halo = new THREE.Mesh(new THREE.PlaneGeometry(w * 2.6, h * 1.7), this.haloMat);
    halo.position.set(0, 0, 0.02); // just in front of the wall, behind the membrane
    halo.renderOrder = -1;
    this.group.add(halo);

    this.membrane = membrane;
    this.target = null;      // room index this portal leads to
    this.reason = null;      // routing reason key
  }

  update(t, hover) {
    this.membraneMat.uniforms.uTime.value = t;
    const boost = hover ? 1.0 : 0.0;
    this.haloMat.opacity = Math.min(0.85, 0.36 + 0.18 * (0.5 + 0.5 * Math.sin(t * 1.8)) + boost * 0.3);
    this.rim.material.opacity = hover ? 1.0 : 0.85;
    this.rim.material.color.set(hover ? "#ffffff" : "#6ee7ff");
  }

  /** World-space distance of a point from the portal plane + local extents check. */
  contains(camPos) {
    const local = this.group.worldToLocal(camPos.clone());
    const w = this.def.width, h = this.def.height;
    return (
      Math.abs(local.z) < 0.42 &&
      local.x > -w / 2 - 0.18 && local.x < w / 2 + 0.18 &&
      local.y > -h / 2 - 0.25 && local.y < h / 2 + 0.25
    );
  }

  planeCenterWorld() {
    return this.group.position.clone();
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

function makeHaloTexture() {
  const s = 128;
  const cv = document.createElement("canvas");
  cv.width = s; cv.height = s;
  const ctx = cv.getContext("2d");
  const g = ctx.createRadialGradient(s / 2, s / 2, s * 0.12, s / 2, s / 2, s / 2);
  g.addColorStop(0, "rgba(110,231,255,0.55)");
  g.addColorStop(0.5, "rgba(167,139,250,0.18)");
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
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
      const overlap = rooms[i].style_tags.filter((t) => cur.style_tags.includes(t)).length;
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
