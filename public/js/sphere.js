/**
 * PANODROME — Stage 1 · Pure Optical Sphere
 *
 * ARCHITECTURAL INTEGRITY RULE (locked 2026-11-02):
 * A 360° architectural render MUST keep 100% razor-sharp, plumb-straight
 * vertical lines at all times. Therefore the room is rendered on a PRISTINE,
 * UNDISPLACED high-density sphere — zero vertex warping, zero depth
 * displacement, zero baked noise. The "feel of walking" is produced purely
 * optically (FOV glide + micro-parallax) in controls.js — never by bending
 * geometry.
 *
 *   · SphereGeometry(500, 128, 96) — silky-smooth silhouette, exact sphere
 *   · 4K equirect texture, SRGBColorSpace
 *   · anisotropy = renderer.capabilities.getMaxAnisotropy() for crisp floors
 *     at grazing angles
 */
import * as THREE from "three";

export const SPHERE_RADIUS = 500;

/** Direction for horizontal fraction (0..1 across the image) and pitch (-90..+90 deg). */
export function equirectDir(frac, pitchDeg = 0) {
  const phi = 2 * Math.PI * frac;
  const theta = Math.PI / 2 - (pitchDeg * Math.PI) / 180;
  const st = Math.sin(theta);
  return new THREE.Vector3(-Math.cos(phi) * st, Math.cos(theta), Math.sin(phi) * st);
}

/**
 * Build the room: a pristine textured sphere centred on the pano shoot point.
 * @param {object} room   room record from rooms_db.json
 * @param {THREE.WebGLRenderer} renderer  for max-anisotropy
 * @returns {Promise<{mesh:THREE.Mesh, dispose:Function}>}
 */
export function buildRoomSphere(room, renderer) {
  return new Promise((resolve, reject) => {
    new THREE.TextureLoader().load(
      room.panorama,
      (texture) => {
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
        texture.wrapS = THREE.RepeatWrapping;   // seam-safe horizontal wrap
        texture.needsUpdate = true;

        const geo = new THREE.SphereGeometry(SPHERE_RADIUS, 128, 96);
        const mat = new THREE.MeshBasicMaterial({
          map: texture,
          side: THREE.BackSide,
        });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.name = "panodrome_room";
        const c = room.camera;
        mesh.position.set(c.x, c.y, c.z);   // sphere centre = pano shoot point

        resolve({
          mesh,
          texture,
          /** Mathematical proof of zero distortion: max |‖v‖−R| over all vertices. */
          radiusDeviation: (() => {
            const pos = geo.attributes.position;
            const v = new THREE.Vector3();
            let maxDev = 0;
            for (let i = 0; i < pos.count; i++) {
              v.fromBufferAttribute(pos, i);
              const dev = Math.abs(v.length() - SPHERE_RADIUS);
              if (dev > maxDev) maxDev = dev;
            }
            return maxDev;
          })(),
          dispose() {
            geo.dispose();
            texture.dispose();
            mat.dispose();
          },
        });
      },
      undefined,
      () => reject(new Error("panorama failed: " + room.panorama))
    );
  });
}

/** Warm the browser cache for the likely-next room (panorama only — no depth needed at runtime). */
export function prefetchRoom(room) {
  if (!room) return;
  const a = new Image();
  a.src = room.panorama;
}
