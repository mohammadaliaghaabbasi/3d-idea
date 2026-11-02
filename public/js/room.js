/**
 * PANODROME — Stage 1.6 · Two-Layer Room (shell volume + 3D furniture)
 *
 * LAYER 1 (this module): the room shell — since Stage 1.5 the equirect
 * panorama is projected onto a TRUE ROOM-SCALE INTERIOR VOLUME (metric
 * shoebox, floor y = 0, plumb walls, per-fragment equirect shader from the
 * capture point). Stage 1.6 swaps the texture source: when the room was
 * processed by skills/skill_360_to_walkable_3d.py, `shell_texture` is the
 * INPAINTED panorama (foreground furniture cleanly erased + background
 * floor/wall reconstructed) — so walking across the floor shows clean
 * carpet/wood, never flattened chalk-art furniture.
 * LAYER 2 (main.js): the extracted furniture renders as true 3D meshes at
 * their measured metric (x, y, z) inside this volume.
 *
 * Laws that NEVER change: floor perfectly flat, walls perfectly plumb,
 * FOV fixed 68/75, zero vertex displacement, raw-sRGB passthrough.
 */
import * as THREE from "three";

export const CORNER_FILLET = 0.35;   // m — vertical wall-corner fillet radius
export const FLOOR_COVE = 0.15;      // m — floor/wall cove radius
const FILLET_SEG = 10;

function buildGeometryParts() {
  const verts = [];
  const idx = [];
  let vCount = 0;

  const vert = (x, y, z) => { verts.push(x, y, z); return vCount++; };
  const quad = (a, b, c, d) => { idx.push(a, b, c, a, c, d); };
  const ruled = (ringA, ringB) => {
    for (let i = 0; i < ringA.length - 1; i++) {
      quad(ringA[i], ringA[i + 1], ringB[i + 1], ringB[i]);
    }
  };

  return { verts, idx, vert, quad, ruled };
}

/**
 * Build the room-volume geometry in WORLD coordinates.
 * Box: x ∈ [-w/2, w/2], z ∈ [-d/2, d/2] (centred on the world origin),
 * floor y = 0, ceiling y = h. The capture point (room.camera) sits inside.
 */
export function buildRoomGeometry(w, d, h) {
  const { verts, idx, vert, quad, ruled } = buildGeometryParts();

  const hw = w / 2, hd = d / 2;
  const fr = Math.min(CORNER_FILLET, hw * 0.45, hd * 0.45);  // corner fillet
  const gr = Math.min(FLOOR_COVE, hw * 0.45, hd * 0.45);      // floor cove

  // ---- floor & ceiling: perfectly flat planes ----
  quad(vert(-hw, 0, -hd), vert(hw, 0, -hd), vert(hw, 0, hd), vert(-hw, 0, hd));
  quad(vert(-hw, h, -hd), vert(hw, h, -hd), vert(hw, h, hd), vert(-hw, h, hd));

  // ---- 4 walls: perfectly flat, perfectly plumb quads ----
  quad(vert(-hw, 0, -hd), vert(-hw, 0, hd), vert(-hw, h, hd), vert(-hw, h, -hd)); // west  x-
  quad(vert(hw, 0, -hd), vert(hw, 0, hd), vert(hw, h, hd), vert(hw, h, -hd));     // east  x+
  quad(vert(-hw, 0, -hd), vert(hw, 0, -hd), vert(hw, h, -hd), vert(-hw, h, -hd)); // north z-
  quad(vert(-hw, 0, hd), vert(hw, 0, hd), vert(hw, h, hd), vert(-hw, h, hd));     // south z+

  // ---- 4 vertical corner fillets: quarter cylinders, full height ----
  // surface point at arc angle a ∈ [0, π/2]: sweeps from one wall to the other
  for (const [sx, sz] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    const bottom = [], top = [];
    for (let i = 0; i <= FILLET_SEG; i++) {
      const a = (i / FILLET_SEG) * Math.PI / 2;
      const x = (hw - fr) + sx * fr * Math.sin(a);
      const z = (hd - fr) + sz * fr * Math.cos(a);
      bottom.push(vert(x, 0, z));
      top.push(vert(x, h, z));
    }
    ruled(bottom, top);
  }

  // ---- 4 floor coves: quarter cylinders along the wall bases ----
  // arc t ∈ [0, π/2]: t=0 lies on the floor plane, t=π/2 lies on the wall
  for (const side of ["west", "east", "north", "south"]) {
    const arcStart = [], arcEnd = [];
    for (let i = 0; i <= FILLET_SEG; i++) {
      const s = i / FILLET_SEG;
      const t = s * Math.PI / 2;
      const y = gr * Math.sin(t);            // 0 → gr above the floor
      const off = gr - gr * Math.cos(t);     // 0 → gr away from the wall
      if (side === "west" || side === "east") {
        const x = side === "west" ? -hw + off : hw - off;
        arcStart.push(vert(x, y, -hd));
        arcEnd.push(vert(x, y, hd));
      } else {
        const z = side === "north" ? -hd + off : hd - off;
        arcStart.push(vert(-hw, y, z));
        arcEnd.push(vert(hw, y, z));
      }
    }
    ruled(arcStart, arcEnd);
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
  geo.setIndex(idx);
  return geo;
}

const FRAG = /* glsl */`
  uniform sampler2D map;
  uniform vec3 uCenter;
  uniform float uFade;
  varying vec3 vWorldPos;
  void main() {
    vec3 d = normalize(vWorldPos - uCenter);
    float u = atan(d.z, -d.x) / 6.28318530718;                  // equirect longitude
    float v = 1.0 - acos(clamp(d.y, -1.0, 1.0)) / 3.14159265359; // equirect latitude
    vec4 tex = texture2D(map, vec2(u, v));
    gl_FragColor = vec4(tex.rgb * uFade, 1.0);
  }
`;
const VERT_SHADER = /* glsl */`
  varying vec3 vWorldPos;
  void main() {
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vWorldPos = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

/**
 * Build the walkable room volume.
 * @returns {Promise<{mesh, texture, geo, stats, setFade, dispose}>}
 *   stats.floorFlatness — max |y| over floor-plane vertices (→ 0: flat law)
 *   stats.wallPlumb     — max off-plane distance over straight-band wall
 *                         vertices between the fillets (→ ~0: plumb law)
 */
export function buildRoomVolume(room, renderer) {
  return new Promise((resolve, reject) => {
    const texUrl = room.shell_texture || room.panorama;   // Stage 1.6: inpainted shell
    new THREE.TextureLoader().load(
      texUrl,
      (texture) => {
        // RAW sRGB passthrough: no decode / no re-encode — byte-exact panorama.
        texture.wrapS = THREE.RepeatWrapping;
        texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
        texture.needsUpdate = true;

        const { width, height, depth } = room.room_shape;
        const geo = buildRoomGeometry(width, depth, height);

        const mat = new THREE.ShaderMaterial({
          vertexShader: VERT_SHADER,
          fragmentShader: FRAG,
          uniforms: {
            map: { value: texture },
            uCenter: { value: new THREE.Vector3(room.camera.x, room.camera.y, room.camera.z) },
            uFade: { value: 1 },
          },
          side: THREE.DoubleSide,
          depthWrite: true,
        });

        const mesh = new THREE.Mesh(geo, mat);
        mesh.name = "panodrome_room";
        mesh.frustumCulled = false;

        // ---- mathematical flatness proofs (the E2E contract) ----
        // floor: the first 4 vertices of buildRoomGeometry are the floor quad
        const pos = geo.attributes.position;
        let floorFlat = 0;
        for (let i = 0; i < 4; i++) {
          floorFlat = Math.max(floorFlat, Math.abs(pos.getY(i)));
        }
        // walls: verts in the straight band between the fillets, above the
        // cove, must lie exactly on a wall plane (x = ±w/2 or z = ±d/2)
        let wallPlumb = 0;
        const fr = Math.min(CORNER_FILLET, (width / 2) * 0.45, (depth / 2) * 0.45);
        const gr = Math.min(FLOOR_COVE, (width / 2) * 0.45, (depth / 2) * 0.45);
        for (let i = 0; i < pos.count; i++) {
          const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
          if (y < gr * 0.999 || y > height - 1e-6) continue;
          const onX = Math.min(Math.abs(x + width / 2), Math.abs(x - width / 2));
          const onZ = Math.min(Math.abs(z + depth / 2), Math.abs(z - depth / 2));
          const inCornerX = Math.abs(x) > width / 2 - fr - 1e-6;
          const inCornerZ = Math.abs(z) > depth / 2 - fr - 1e-6;
          if (inCornerX && inCornerZ) continue;   // fillet band
          wallPlumb = Math.max(wallPlumb, Math.min(onX, onZ));
        }

        resolve({
          mesh,
          texture,
          geo,
          stats: {
            width, depth, height,
            floorFlatness: floorFlat,
            wallPlumb: Math.max(0, wallPlumb),
            textureSize: [texture.image.width, texture.image.height],
          },
          setFade(f) { mat.uniforms.uFade.value = f; },
          dispose() {
            geo.dispose();
            texture.dispose();
            mat.dispose();
          },
        });
      },
      undefined,
      () => reject(new Error("shell/panorama failed: " + texUrl))
    );
  });
}

/** Warm the browser cache for the likely-next room. */
export function prefetchRoom(room) {
  if (!room) return;
  const a = new Image();
  a.src = room.shell_texture || room.panorama;
  if (room.furniture && room.furniture.glb) {
    fetch(room.furniture.glb, { mode: "same-origin" }).catch(() => {});
  }
}
