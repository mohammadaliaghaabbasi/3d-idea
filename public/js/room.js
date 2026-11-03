/**
 * PANODROME — Stage 2.1 · Room Volumes (TRUE-WALK EVERYWHERE)
 * ============================================================================
 * Every room is a HYBRID with two aligned layers (owner order 2026-11-03):
 *
 *   · TRUE-3D WALK SCENE (default) — the room's bespoke .glb architectural
 *     model (skills/build_all_3d_rooms.py), materials assembled from the
 *     shared palette (materials.js), lit by the authored light rig + the
 *     original panorama as PMREM environment light, sky dome outside the
 *     windows.  REAL geometry — multi-metre 6DoF walking can never warp it.
 *
 *   · 360° PHOTO REFERENCE — the original 4K equirect photograph on a pure
 *     SphereGeometry(500, 128, 96), ZERO vertex displacement, seam-wrapped
 *     at load (LAW 1 preserved).  From the optical capture station it is
 *     photograph-perfect — the "🌐 عکس ۳۶۰ اصلی" toggle.  The sphere renders
 *     last with depthTest off so photo↔walk is a clean 350 ms crossfade.
 */
import * as THREE from "three";
import { GLTFLoader } from "../vendor/GLTFLoader-0.160.0.js";
import { SurfaceRegistry } from "./materials.js";

/* ---------------------------------------------------------- owner laws */
export const PANO_SPHERE_RADIUS = 500;   // m  — SphereGeometry(500, 128, 96)
export const PANO_SEG_W = 128;
export const PANO_SEG_H = 96;
export const SEAM_BLEND_PX = 24;         // px cross-dissolve band at u=0/1

/* ------------------------------------------------------------ pano sphere */

function loadSeamWrappedTexture(url, renderer) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      try {
        const W = img.naturalWidth, H = img.naturalHeight;
        const cv = document.createElement("canvas");
        cv.width = W; cv.height = H;
        const ctx = cv.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0);
        const pad = Math.min(SEAM_BLEND_PX, Math.floor(W / 8));
        for (let k = 0; k < pad; k++) {
          const w = 0.5 * (1 - k / pad);
          const L = ctx.getImageData(k, 0, 1, H);
          const R = ctx.getImageData(W - 1 - k, 0, 1, H);
          for (let i = 0; i < H * 4; i++) {
            const l = L.data[i], r = R.data[i];
            L.data[i] = l * (1 - w) + r * w;
            R.data[i] = r * (1 - w) + l * w;
          }
          ctx.putImageData(L, k, 0);
          ctx.putImageData(R, W - 1 - k, 0);
        }
        const tex = new THREE.CanvasTexture(cv);
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.wrapS = THREE.RepeatWrapping;
        tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
        tex.mapping = THREE.EquirectangularReflectionMapping;
        tex.needsUpdate = true;
        resolve(tex);
      } catch (err) { reject(err); }
    };
    img.onerror = () => reject(new Error("panorama failed: " + url));
    img.src = url;
  });
}

/** Build the ZERO-WARP photo sphere (identical law to Stage 2.0). */
export async function buildPanoSphere(room, renderer) {
  const capture = new THREE.Vector3(room.camera.x, room.camera.y, room.camera.z);
  const texture = await loadSeamWrappedTexture(room.panorama, renderer);

  const geo = new THREE.SphereGeometry(PANO_SPHERE_RADIUS, PANO_SEG_W, PANO_SEG_H);
  const mat = new THREE.MeshBasicMaterial({
    map: texture,
    side: THREE.BackSide,
    toneMapped: false,
    transparent: true,
    opacity: 0,
    depthWrite: false,
    depthTest: false,       // renders over the 3D scene — clean crossfade
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.name = "panodrome_pano_sphere";
  mesh.position.copy(capture);
  mesh.renderOrder = 999;
  mesh.frustumCulled = false;
  mesh.visible = false;

  return {
    mesh,
    texture,
    capture,
    stats: {
      radius: PANO_SPHERE_RADIUS,
      segW: PANO_SEG_W,
      segH: PANO_SEG_H,
      seamBlendPx: SEAM_BLEND_PX,
    },
    setFade(f) {
      mat.opacity = f;
      mesh.visible = f > 0.005;
    },
    dispose() { geo.dispose(); texture.dispose(); mat.dispose(); },
  };
}

/* ------------------------------------------------------------- sky dome */

function buildSky(room) {
  const sky = room.sky || {};
  const top = new THREE.Color(sky.zenith || "#7fb2e5");
  const bottom = new THREE.Color(sky.horizon || "#e8eef4");
  const sun = new THREE.Color(sky.sun || "#fff2dc");
  const sunDir = new THREE.Vector3(...(sky.sun_dir || [-0.55, 0.5, 0.25])).normalize();
  const geo = new THREE.SphereGeometry(450, 32, 20);
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    uniforms: {
      uTop: { value: top },
      uBottom: { value: bottom },
      uSun: { value: sun },
      uSunDir: { value: sunDir },
    },
    vertexShader: /* glsl */`
      varying vec3 vDir;
      void main() {
        vDir = normalize(position);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: /* glsl */`
      uniform vec3 uTop; uniform vec3 uBottom; uniform vec3 uSun;
      uniform vec3 uSunDir;
      varying vec3 vDir;
      void main() {
        float h = clamp(vDir.y * 0.5 + 0.5, 0.0, 1.0);
        vec3 col = mix(uBottom, uTop, pow(h, 0.85));
        float d = max(dot(normalize(vDir), uSunDir), 0.0);
        col += uSun * pow(d, 42.0) * 0.9;
        col += uSun * pow(d, 5.0) * 0.10;
        gl_FragColor = vec4(col, 1.0);
      }`,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.name = "panodrome_sky";
  mesh.frustumCulled = false;
  return mesh;
}

/* ------------------------------------------------------------- true 3D */

export function buildTrue3DRoom(room, renderer) {
  return new Promise((resolve, reject) => {
    const loader = new GLTFLoader();
    loader.load(room.glb, async (gltf) => {
      const group = new THREE.Group();
      group.name = "panodrome_true3d_room";

      const root = gltf.scene || gltf.scenes[0];
      root.name = room.id + "_glb";

      // ---- palette materials ("x_<key>#<kind>") + surface registry ----
      const surfaces = new SurfaceRegistry();
      await surfaces.bind(root);

      // ---- authored light rig ----
      const lights = [];
      const hemi = new THREE.HemisphereLight(0xdfeaf5, 0x8a7a66, 0.55);
      group.add(hemi); lights.push(hemi);
      for (const L of (room.walk && room.walk.lights) || []) {
        if (L.type === "sun") {
          const sun = new THREE.DirectionalLight(L.color || 0xfff0dd, L.intensity ?? 2.4);
          sun.position.set(...L.pos);
          group.add(sun); lights.push(sun);
        } else if (L.type === "spot") {
          const p = new THREE.PointLight(L.color || 0xffe6c4, L.intensity ?? 0.55, L.distance ?? 7, 2);
          p.position.set(...L.pos);
          group.add(p); lights.push(p);
        }
      }
      const sky = buildSky(room);
      group.add(root);
      group.add(sky);

      let meshes = 0, tris = 0;
      root.traverse((o) => {
        if (o.isMesh) {
          meshes++;
          tris += o.geometry.index ? o.geometry.index.count / 3 : o.geometry.attributes.position.count / 3;
        }
      });

      resolve({
        mesh: group,
        root,
        texture: null,
        kind: "true3d",
        surfaces,
        lights,
        stats: {
          kind: "true3d",
          glb: room.glb,
          meshes,
          tris: Math.round(tris),
          lights: lights.length,
        },
        dispose() {
          root.traverse((o) => {
            if (o.isMesh) {
              o.geometry?.dispose?.();
            }
          });
          sky.geometry.dispose(); sky.material.dispose();
          for (const l of lights) l.dispose?.();
        },
      });
    }, undefined, () => reject(new Error("glb failed: " + room.glb)));
  });
}

/* ------------------------------------------------------------- public API */

/**
 * Build any room as a hybrid: the true-3D walk scene (+ photo sphere when the
 * room has a panorama).  Resolves as soon as the GLB is walkable; the photo
 * sphere attaches when it arrives (photo toggle awaits it).
 */
export function buildRoomVolume(room, renderer) {
  const panoPromise = room.panorama
    ? buildPanoSphere(room, renderer).catch(() => null)
    : Promise.resolve(null);

  return buildTrue3DRoom(room, renderer).then((t3) => {
    // pano as PMREM environment light (image-based interior lighting)
    const envPromise = panoPromise.then((p) => {
      if (!p || !renderer) return null;
      try {
        const pmrem = new THREE.PMREMGenerator(renderer);
        const env = pmrem.fromEquirectangular(p.texture);
        pmrem.dispose();
        return env.texture;
      } catch (e) { return null; }
    });

    return {
      mesh: t3.mesh,
      root: t3.root,
      kind: room.panorama ? "hybrid" : "true3d",
      surfaces: t3.surfaces,
      stats: Object.assign({
        kind: room.panorama ? "hybrid" : "true3d",
        sphere: null,
        textureSize: null,
      }, t3.stats),
      panoReady: panoPromise.then((p) => {
        if (!p) return null;
        t3.mesh.add(p.mesh);                       // sphere inside the same group
        return p;
      }),
      envReady: envPromise.then((env) => env),
      setPhotoSphere(opacity) { return opacity; },   // patched by main after attach
      setFade() {},
      dispose() {
        panoPromise.then((p) => p && p.dispose());
        t3.dispose();
      },
    };
  });
}

/** Warm the browser cache for the likely-next room. */
export function prefetchRoom(room) {
  if (!room) return;
  if (room.glb) fetch(room.glb, { mode: "same-origin" }).catch(() => {});
  if (room.panorama) {
    const a = new Image();
    a.src = room.panorama;
  }
}
