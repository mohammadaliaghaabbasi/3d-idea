/**
 * PANODROME — Panorama → walkable mesh
 *
 * Builds a displaced sphere from the equirect panorama + two-channel depth PNG:
 * every sphere vertex is pushed along its direction by the sampled depth (meters),
 * so the textured sphere becomes the actual room volume — real 6DoF parallax.
 *
 * Geometry convention matches skills/ingest_polyhaven.py exactly:
 *   uv.x = px/W (image left = 0), uv.v = 1 at image top,
 *   dir(u,θ) = (-cos(2πu)·sinθ, cosθ, sin(2πu)·sinθ)   [three.js SphereGeometry]
 */
import * as THREE from "three";

/** Direction for horizontal fraction (0..1 across the image) and pitch (-90..+90 deg). */
export function equirectDir(frac, pitchDeg = 0) {
  const phi = 2 * Math.PI * frac;
  const theta = Math.PI / 2 - (pitchDeg * Math.PI) / 180;
  const st = Math.sin(theta);
  return new THREE.Vector3(-Math.cos(phi) * st, Math.cos(theta), Math.sin(phi) * st);
}

function loadImage(url) {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = () => rej(new Error("image failed: " + url));
    img.src = url;
  });
}

/** Decode the two-channel PNG (R=hi, G=lo) into a Float32 depth field in meters. */
async function loadDepthField(room, base) {
  const img = await loadImage(base + room.depth_map);
  const w = img.naturalWidth, h = img.naturalHeight;
  const cv = document.createElement("canvas");
  cv.width = w; cv.height = h;
  const ctx = cv.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0);
  const data = ctx.getImageData(0, 0, w, h).data;
  const f = new Float32Array(w * h);
  const maxD = room.depth_max || 10;
  for (let i = 0, p = 0; i < f.length; i++, p += 4) {
    f[i] = ((data[p] * 256 + data[p + 1]) / 65535) * maxD;
  }
  return { field: f, w, h };
}

/** Bilinear depth sample with horizontal wrap. uv: three.js uv (x, y with y=1 top). */
function sampleDepth(depth, u, v) {
  const { field, w, h } = depth;
  const x = ((u % 1) + 1) % 1 * (w - 1);
  const y = Math.min(Math.max((1 - v) * (h - 1), 0), h - 1);
  const x0 = Math.floor(x), y0 = Math.floor(y);
  const x1 = (x0 + 1) % w, y1 = Math.min(y0 + 1, h - 1);
  const fx = x - x0, fy = y - y0;
  const a = field[y0 * w + x0], b = field[y0 * w + x1];
  const c = field[y1 * w + x0], d = field[y1 * w + x1];
  return a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy;
}

/**
 * Build the room mesh.
 * @returns {Promise<{mesh: THREE.Mesh, dispose: Function}>}
 */
export async function buildRoomMesh(room, base = "") {
  const [texture, depth] = await Promise.all([
    new Promise((res, rej) => {
      new THREE.TextureLoader().load(
        base + room.panorama,
        (t) => {
          t.colorSpace = THREE.SRGBColorSpace;
          t.anisotropy = 8;
          res(t);
        },
        undefined,
        () => rej(new Error("panorama failed"))
      );
    }),
    loadDepthField(room, base),
  ]);

  const geo = new THREE.SphereGeometry(1, 256, 128);
  const pos = geo.attributes.position;
  const uv = geo.attributes.uv;
  const v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).normalize();          // unit direction (radius 1 sphere)
    const r = sampleDepth(depth, uv.getX(i), uv.getY(i));
    pos.setXYZ(i, v.x * r, v.y * r, v.z * r);
  }
  pos.needsUpdate = true;
  geo.computeBoundingSphere();

  const mat = new THREE.MeshBasicMaterial({
    map: texture,
    side: THREE.BackSide,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.name = "panodrome_room";
  // Vertices are stored relative to the pano shoot position (cx, eye, cz):
  // shift the mesh so the room lands in world coords (floor at y=0) and the
  // camera starts exactly at the projection centre -> pano-exact initial view.
  mesh.position.set(room.camera.x, room.camera.y, room.camera.z);

  const dispose = () => {
    geo.dispose();
    texture.dispose();
    mat.dispose();
  };
  return { mesh, dispose };
}

/** Warm the browser cache for likely-next rooms. */
export function prefetchRoom(room, base = "") {
  if (!room) return;
  const a = new Image(); a.src = base + room.panorama;
  const b = new Image(); b.src = base + room.depth_map;
}
