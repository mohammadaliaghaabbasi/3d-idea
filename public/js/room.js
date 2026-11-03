/**
 * PANODROME — Stage 1.6.1 · Relief Dome Room (EMERGENCY VISUAL RESTORATION)
 * ============================================================================
 * Owner order 2026-11-02 (live iPhone audit rejected Stage 1.6):
 *   · Rule A — the ORIGINAL crisp pano_4k.jpg is the ONLY texture.  No
 *     Telea/NS inpainting, no shell swap, no 122px guard bands, ever.
 *   · Rule B — NO depth-cut furniture extrusions (no edge tearing, no
 *     back-caps, no spiky GLBs).  Instead: ONE watertight, ground-
 *     flattened radial RELIEF DOME — a sphere grid around the capture
 *     point displaced by a smooth σ=18px Gaussian depth-relief field
 *     (baked offline by skills/stage161_dome_relief.py into
 *     public/assets/relief/<id>.png, u16 split across the R+G bytes).
 *     Furniture stays painted in the photograph AT ITS TRUE RADIAL
 *     DEPTH (soft relief bulges) -> genuine parallax, zero saw-tooth,
 *     zero smudges, zero torn edges.
 *
 * The per-fragment equirect shader is UNCHANGED (Stage-1.5 law): every
 * fragment computes its pano UV from the direction capture->fragment, so
 * the projection is PIXEL-EXACT at the capture point and stays correct
 * from anywhere inside the dome.  Floor is EXACTLY y=0 (flat-floor law:
 * the bake snaps floor rays to the analytic plane; steep rows are forced
 * exactly planar).  FOV stays fixed; the dome never zooms.
 *
 * Fallback: if a room has no relief field (or the PNG fails to load) we
 * silently build the Stage-1.5 metric shoebox — the site always works.
 */
import * as THREE from "three";

export const CORNER_FILLET = 0.35;   // m — box-fallback corner fillet radius
export const FLOOR_COVE = 0.15;      // m — box-fallback floor/wall cove radius
const FILLET_SEG = 10;

const DOME_SEG = 384;                // azimuth bins (0.94°)
const DOME_ROWS = 168;               // elevation rows (1.07°)

/* ------------------------------------------------------------ box fallback */

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

/** Stage-1.5 metric shoebox (fallback when no relief field exists). */
export function buildRoomGeometry(w, d, h) {
  const { verts, idx, vert, quad, ruled } = buildGeometryParts();

  const hw = w / 2, hd = d / 2;
  const fr = Math.min(CORNER_FILLET, hw * 0.45, hd * 0.45);
  const gr = Math.min(FLOOR_COVE, hw * 0.45, hd * 0.45);

  quad(vert(-hw, 0, -hd), vert(hw, 0, -hd), vert(hw, 0, hd), vert(-hw, 0, hd));
  quad(vert(-hw, h, -hd), vert(hw, h, -hd), vert(hw, h, hd), vert(-hw, h, hd));

  quad(vert(-hw, 0, -hd), vert(-hw, 0, hd), vert(-hw, h, hd), vert(-hw, h, -hd));
  quad(vert(hw, 0, -hd), vert(hw, 0, hd), vert(hw, h, hd), vert(hw, h, -hd));
  quad(vert(-hw, 0, -hd), vert(hw, 0, -hd), vert(hw, h, -hd), vert(-hw, h, -hd));
  quad(vert(-hw, 0, hd), vert(hw, 0, hd), vert(hw, h, hd), vert(-hw, h, hd));

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

  for (const side of ["west", "east", "north", "south"]) {
    const arcStart = [], arcEnd = [];
    for (let i = 0; i <= FILLET_SEG; i++) {
      const t = (i / FILLET_SEG) * Math.PI / 2;
      const y = gr * Math.sin(t);
      const off = gr - gr * Math.cos(t);
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

/* -------------------------------------------------------- relief field I/O */

/**
 * Load the baked radial relief field (u16 split across PNG R+G channels).
 * @returns {Promise<null | {data: Float32Array, w:number, h:number,
 *                            rmin:number, rmax:number}>}
 */
export function loadReliefField(room) {
  const rel = room.walk && room.walk.relief;
  if (!rel || !rel.url) return Promise.resolve(null);
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      try {
        const cv = document.createElement("canvas");
        cv.width = rel.w;
        cv.height = rel.h;
        const ctx = cv.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0, rel.w, rel.h);
        const px = ctx.getImageData(0, 0, rel.w, rel.h).data;
        const n = rel.w * rel.h;
        const data = new Float32Array(n);
        const span = rel.rmax - rel.rmin;
        for (let i = 0; i < n; i++) {
          const q = px[i * 4] * 256 + px[i * 4 + 1];       // R = hi byte, G = lo
          data[i] = rel.rmin + (q / 65535) * span;
        }
        resolve({ data, w: rel.w, h: rel.h, rmin: rel.rmin, rmax: rel.rmax });
      } catch (err) {
        console.warn("relief decode failed (box fallback):", err);
        resolve(null);
      }
    };
    img.onerror = () => { console.warn("relief png failed (box fallback):", rel.url); resolve(null); };
    img.src = rel.url;
  });
}

/** Bilinear sample of the field. u wraps (equirect seam), v clamps. */
function sampleField(f, u, v) {
  const w = f.w, h = f.h, d = f.data;
  let x = u * w - 0.5;
  x = ((x % w) + w) % w;                                  // wrap x
  const y = Math.min(h - 1.001, Math.max(0, v * h - 0.5)); // clamp y
  const x0 = Math.floor(x), y0 = Math.floor(y);
  const x1 = (x0 + 1) % w, y1 = Math.min(y0 + 1, h - 1);
  const fx = x - x0, fy = y - y0;
  const a = d[y0 * w + x0], b = d[y0 * w + x1];
  const c = d[y1 * w + x0], e = d[y1 * w + x1];
  return a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + e * fx * fy;
}

/* ------------------------------------------------------------ relief dome */

/**
 * Watertight ground-flattened radial relief dome.
 * Grid: DOME_SEG x DOME_ROWS around the capture point; vertex = capture +
 * ray(θ,φ)·R(θ,φ) with the SAME equirect convention as the shader
 * (u = atan2(dz,-dx)/2π; row 0 = zenith).  Poles capped with tiny fans
 * (the nadir cap sits EXACTLY on y=0 — flat-floor law).
 */
export function buildDomeGeometry(field, capture) {
  const SEG = DOME_SEG, ROWS = DOME_ROWS;
  const camY = capture.y;
  const rad = new Float32Array(SEG * ROWS);
  const positions = new Float32Array((SEG * ROWS + 2) * 3);

  // φ(v): v = (0.5 - φ/π)  →  v 0 = zenith, 1 = nadir (matches pano rows)
  for (let j = 0; j < ROWS; j++) {
    const v = (j + 0.5) / ROWS;
    const phi = (0.5 - v) * Math.PI;
    const sinP = Math.sin(phi), cosP = Math.cos(phi);
    // FLAT-FLOOR LAW: steep rows are provably floor (the bake snaps them
    // exactly planar) — force the ANALYTIC planar radius so bilinear
    // sampling at the -50° field boundary can never reintroduce wobble.
    const isSteepFloor = phi < -55 * Math.PI / 180;
    const planarR = camY / Math.max(-sinP, 1e-6);
    for (let i = 0; i < SEG; i++) {
      const u = (i + 0.5) / SEG;
      const theta = u * Math.PI * 2;
      const R = isSteepFloor ? planarR : sampleField(field, u, v);
      rad[j * SEG + i] = R;
      const k = (j * SEG + i) * 3;
      // dir = (-cosφ·cosθ, sinφ, cosφ·sinθ) — room.js / shader convention
      positions[k] = capture.x + (-cosP * Math.cos(theta)) * R;
      positions[k + 1] = camY + sinP * R;
      positions[k + 2] = capture.z + (cosP * Math.sin(theta)) * R;
    }
  }

  const idx = new Uint32Array(SEG * ROWS * 6 + SEG * 3 * 2);
  let t = 0;
  for (let j = 0; j < ROWS - 1; j++) {
    for (let i = 0; i < SEG; i++) {
      const i2 = (i + 1) % SEG;                            // x-wrap seam
      const a = j * SEG + i, b = j * SEG + i2;
      const c = (j + 1) * SEG + i, d = (j + 1) * SEG + i2;
      idx[t++] = a; idx[t++] = c; idx[t++] = d;
      idx[t++] = a; idx[t++] = d; idx[t++] = b;
    }
  }
  // pole caps: last two verts
  const topIdx = SEG * ROWS;          // zenith cap
  const botIdx = topIdx + 1;          // nadir cap (EXACTLY y = 0)
  // zenith cap point: mean of the top ring, projected on the up-ray
  let topR = 0;
  for (let i = 0; i < SEG; i++) topR += rad[i];
  topR /= SEG;
  positions[topIdx * 3] = capture.x;
  positions[topIdx * 3 + 1] = camY + topR;
  positions[topIdx * 3 + 2] = capture.z;
  positions[botIdx * 3] = capture.x;
  positions[botIdx * 3 + 1] = 0;                          // flat-floor law
  positions[botIdx * 3 + 2] = capture.z;
  for (let i = 0; i < SEG; i++) {
    const i2 = (i + 1) % SEG;
    idx[t++] = topIdx; idx[t++] = i2; idx[t++] = i;       // zenith fan
    const last = (ROWS - 1) * SEG;
    idx[t++] = botIdx; idx[t++] = last + i; idx[t++] = last + i2;  // nadir fan
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setIndex(new THREE.BufferAttribute(idx.slice(0, t), 1));

  /* ---- mathematical proofs (the E2E contract) ---- */
  // 1) EXACT floor: rows with φ < -56° are analytically planar (override)
  let exactFloor = 0;
  for (let j = 0; j < ROWS; j++) {
    const phi = (0.5 - (j + 0.5) / ROWS) * Math.PI;
    if (phi > -56 * Math.PI / 180) continue;
    for (let i = 0; i < SEG; i++) {
      const y = positions[(j * SEG + i) * 3 + 1];
      if (Math.abs(y) < 0.05) exactFloor = Math.max(exactFloor, Math.abs(y));
    }
  }
  // 2) floor-planarity: any vert within 2cm of the floor is floor-ish
  let floorDev = 0;
  for (let k = 0; k < SEG * ROWS; k++) {
    const y = positions[k * 3 + 1];
    if (Math.abs(y) < 0.02) floorDev = Math.max(floorDev, Math.abs(y));
  }
  // 3) saw-tooth guard (slope-reversal height) on the sampled radii
  let zigzag = 0;
  for (let j = 0; j < ROWS; j++) {
    for (let i = 0; i < SEG; i++) {
      const i0 = j * SEG + ((i + SEG - 1) % SEG);
      const i1 = j * SEG + i;
      const i2 = j * SEG + ((i + 1) % SEG);
      const s1 = rad[i1] - rad[i0], s2 = rad[i2] - rad[i1];
      if (s1 * s2 < 0) zigzag = Math.max(zigzag, Math.min(Math.abs(s1), Math.abs(s2)));
      const j2 = Math.min(j + 1, ROWS - 1);
      const v1 = rad[j2 * SEG + i] - rad[i1], v0 = rad[i1] - rad[Math.max(j - 1, 0) * SEG + i];
      if (v0 * v1 < 0) zigzag = Math.max(zigzag, Math.min(Math.abs(v0), Math.abs(v1)));
    }
  }
  let minR = Infinity, maxR = 0;
  for (let i = 0; i < rad.length; i++) { minR = Math.min(minR, rad[i]); maxR = Math.max(maxR, rad[i]); }

  // 4) PLUMB-LINE proof (owner law 1.6.2): in the WALL band (φ 2..15°) the
  //    horizontal distance R·cosφ must be constant per azimuth wherever the
  //    surface is structural wall (furniture bulges deviate — they are
  //    objects, not structure).  Band 2..15° matches the bake-side proof:
  //    every room's photographed ceiling starts ABOVE 15° elevation
  //    (tightest: ballroom far bays 18.9°), so measured ceilings/chandeliers
  //    at 15-30° never pollute the structural verdict.
  const devs = [];
  const r2d = Math.PI / 180;
  for (let i = 0; i < SEG; i++) {
    const col = [];
    for (let j = 0; j < ROWS; j++) {
      const phi = (0.5 - (j + 0.5) / ROWS) * Math.PI;
      if (phi < 2 * r2d || phi > 15 * r2d) continue;
      col.push(rad[j * SEG + i] * Math.cos(phi));
    }
    if (col.length < 3) continue;
    col.sort((a, b) => a - b);
    const med = col[Math.floor(col.length / 2)];
    for (const h of col) devs.push(Math.abs(h - med));
  }
  devs.sort((a, b) => a - b);
  const pct = (q) => (devs.length ? devs[Math.min(devs.length - 1, Math.floor(q * devs.length))] : 0);
  const plumbP50 = pct(0.5);
  const plumbP90 = pct(0.9);

  const stats = {
    dome: {
      verts: SEG * ROWS + 2,
      tris: t / 3,
      minR: Math.round(minR * 1000) / 1000,
      maxR: Math.round(maxR * 1000) / 1000,
      zigzag: Math.round(zigzag * 1000) / 1000,
      exactFloor: Math.round(exactFloor * 100000) / 100000,
      plumbP50: Math.round(plumbP50 * 10000) / 10000,
      plumbP90: Math.round(plumbP90 * 10000) / 10000,
    },
    floorFlatness: Math.round(exactFloor * 100000) / 100000,   // strict law
    floorPlanarity: Math.round(floorDev * 100000) / 100000,    // incl. skirts
  };
  return { geo, stats };
}

/* ---------------------------------------------------------------- shaders */

/* STITCH DE-SHEAR (stage 1.6.2c): the source pano's own stitcher seam
 * excursion (measured per edge in the survey skills) is undone at
 * SAMPLING time — u' = u + lut(v)·win(u) — so the sheared source columns
 * land back on true plumb fragment columns.  Rule A: the pano file is
 * NEVER modified.  The per-edge LUT is a 64-bin u16-packed DataTexture
 * (same R=hi/G=lo packing as the relief field; hardware filtering would
 * corrupt the byte packing, so NearestFilter + manual linear interp).
 */
const STITCH_UNIFORMS = /* glsl */`
  uniform sampler2D uStTex;   // 64 x N u16-packed de-shear LUTs
  uniform int uStN;          // number of measured edges (0..4)
  uniform vec4 uStBand;      // (r0, r1, lo, range) -- V band + LUT packing
  uniform vec4 uStA[4];      // per edge: (u, half, blend, 0)
`;
const STITCH_CODE = /* glsl */`
    float vS = 1.0 - v;
    float rowGate = smoothstep(uStBand.x - 0.03, uStBand.x + 0.03, vS)
                 * (1.0 - smoothstep(uStBand.y - 0.03, uStBand.y + 0.03, vS));
    if (rowGate > 0.001) {
      float span = max(uStBand.y - uStBand.x, 1e-4);
      float pos = clamp((vS - uStBand.x) / span, 0.0, 0.9999) * 64.0;
      float b0 = floor(pos), ft = pos - b0;
      for (int k = 0; k < 4; k++) {
        if (k >= uStN) break;
        vec4 A = uStA[k];
        float du = u - A.x;
        du -= floor(du + 0.5);
        float w = 1.0 - smoothstep(A.y, A.y + A.z, abs(du));
        if (w > 0.002) {
          float ty = (float(k) + 0.5) / float(uStN);
          vec4 t0 = texture2D(uStTex, vec2((b0 + 0.5) / 64.0, ty));
          vec4 t1 = texture2D(uStTex, vec2((min(b0 + 1.0, 63.0) + 0.5) / 64.0, ty));
          float q = mix(t0.r * 256.0 + t0.g, t1.r * 256.0 + t1.g, ft);
          u += (uStBand.z + q / 65535.0 * uStBand.w) * w * rowGate;
        }
      }
    }
`;

function buildFrag(stitch) {
  return /* glsl */`
  uniform sampler2D map;
  uniform vec3 uCenter;
  uniform float uFade;
  varying vec3 vWorldPos;
  ${stitch ? STITCH_UNIFORMS : ""}
  void main() {
    vec3 d = normalize(vWorldPos - uCenter);
    float u = atan(d.z, -d.x) / 6.28318530718;                  // equirect longitude
    float v = 1.0 - acos(clamp(d.y, -1.0, 1.0)) / 3.14159265359; // equirect latitude
    ${stitch ? STITCH_CODE : ""}
    vec4 tex = texture2D(map, vec2(u, v));
    gl_FragColor = vec4(tex.rgb * uFade, 1.0);
  }
`;
}

/** Build the de-shear uniforms + LUT texture from room.walk.relief.stitch.
 *  @returns {{uniforms, texture}|null} */
function buildStitch(room, renderer) {
  const st = room.walk && room.walk.relief && room.walk.relief.stitch;
  if (!st || !Array.isArray(st.edges) || st.edges.length === 0) return null;
  const n = Math.min(st.edges.length, 4);
  const bins = st.bins || 64;
  const lo = st.lo, range = Math.max(st.range, 1e-9);
  const data = new Uint8Array(bins * n * 4);
  for (let k = 0; k < n; k++) {
    const lut = st.edges[k].lut || [];
    for (let b = 0; b < bins; b++) {
      const val = b < lut.length ? lut[b] : 0;
      const q = Math.max(0, Math.min(65535, Math.round((val - lo) / range * 65535)));
      const o = (k * bins + b) * 4;
      data[o] = q >> 8; data[o + 1] = q & 255;
    }
  }
  const tex = new THREE.DataTexture(data, bins, n, THREE.RGBAFormat, THREE.UnsignedByteType);
  tex.minFilter = THREE.NearestFilter;
  tex.magFilter = THREE.NearestFilter;
  tex.needsUpdate = true;
  const uniforms = {
    uStTex: { value: tex },
    uStN: { value: n },
    uStBand: { value: new THREE.Vector4(st.r0, st.r1, lo, range) },
    uStA: { value: st.edges.slice(0, 4).map(e => new THREE.Vector4(e.u, e.half, e.blend, 0)) },
  };
  return { uniforms, texture: tex };
}
const VERT_SHADER = /* glsl */`
  varying vec3 vWorldPos;
  void main() {
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vWorldPos = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

/* ------------------------------------------------------------- public API */

/**
 * Build the walkable room: relief dome when the room has a baked field,
 * Stage-1.5 metric shoebox otherwise.  The pano texture is ALWAYS the
 * crisp original (Rule A — no inpainted shells).
 * @returns {Promise<{mesh, texture, geo, stats, isDome, setFade,
 *                    wallDistAt, dispose}>}
 */
export function buildRoomVolume(room, renderer) {
  const capture = new THREE.Vector3(room.camera.x, room.camera.y, room.camera.z);
  const { width, height, depth } = room.room_shape;

  return new Promise((resolve, reject) => {
    Promise.all([
      new Promise((res, rej) => new THREE.TextureLoader().load(
        room.panorama, res, undefined,
        () => rej(new Error("panorama failed: " + room.panorama)))),
      loadReliefField(room),
    ]).then(([texture, field]) => {
      // RAW sRGB passthrough: no decode / no re-encode — byte-exact panorama.
      texture.wrapS = THREE.RepeatWrapping;
      texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
      texture.needsUpdate = true;

      let geo, stats, isDome = false, wallDistAt = null;
      if (field) {
        const dome = buildDomeGeometry(field, capture);
        geo = dome.geo;
        stats = dome.stats;
        isDome = true;
        // horizontal wall distance at pano-θ (φ = 0 row) — used to keep the
        // doorway ring floating just in front of the TRUE wall
        wallDistAt = (theta) => {
          const u = ((theta / (Math.PI * 2)) % 1 + 1) % 1;
          return sampleField(field, u, 0.5);
        };
      } else {
        geo = buildRoomGeometry(width, depth, height);
        const pos = geo.attributes.position;
        let floorFlat = 0;
        for (let i = 0; i < 4; i++) floorFlat = Math.max(floorFlat, Math.abs(pos.getY(i)));
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
          if (inCornerX && inCornerZ) continue;
          wallPlumb = Math.max(wallPlumb, Math.min(onX, onZ));
        }
        stats = { width, depth, height, floorFlatness: floorFlat, wallPlumb: Math.max(0, wallPlumb), dome: null };
      }
      stats.textureSize = [texture.image.width, texture.image.height];

      const stitch = buildStitch(room, renderer);
      const mat = new THREE.ShaderMaterial({
        vertexShader: VERT_SHADER,
        fragmentShader: buildFrag(!!stitch),
        uniforms: Object.assign({
          map: { value: texture },
          uCenter: { value: capture.clone() },
          uFade: { value: 1 },
        }, stitch ? stitch.uniforms : {}),
        side: THREE.DoubleSide,
        depthWrite: true,
      });

      const mesh = new THREE.Mesh(geo, mat);
      mesh.name = "panodrome_room";
      mesh.frustumCulled = false;

      resolve({
        mesh,
        texture,
        geo,
        stats,
        isDome,
        setFade(f) { mat.uniforms.uFade.value = f; },
        wallDistAt,
        dispose() {
          geo.dispose();
          texture.dispose();
          if (stitch) { stitch.texture.dispose(); }
          mat.dispose();
        },
      });
    }).catch(reject);
  });
}

/** Warm the browser cache for the likely-next room (pano + relief). */
export function prefetchRoom(room) {
  if (!room) return;
  const a = new Image();
  a.src = room.panorama;
  const rel = room.walk && room.walk.relief;
  if (rel && rel.url) fetch(rel.url, { mode: "same-origin" }).catch(() => {});
}
