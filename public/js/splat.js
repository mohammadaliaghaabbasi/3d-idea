/**
 * SPLAT RENDERER — the appearance lane (docs/17, Lane B2).
 *
 * Loads a 3DGS .ply baked by skills/bake_splat.py and draws it as depth-tested
 * soft discs. Simple on purpose: no sorting pass, no EWA-ellipse math, ~2 ms of
 * CPU. What matters for walking is that the pixels are REAL lifted pixels and
 * that collision still comes from the metric proxy (collider.js), never here.
 *
 * Usage:
 *   const splat = await loadSplat("assets/splats/cabin.ply");
 *   const mesh = createSplat(splat, { pixelRatio: 2 });
 *   scene.add(mesh);            // sphere must be hidden by the caller
 *   mesh.material.uniforms.uScale.value = splatScaleFor(camera, renderer);
 */

import * as THREE from "three";

const EXPECTED = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2",
                  "opacity", "scale_0", "scale_1", "scale_2"];

/** Parse a binary little-endian 3DGS PLY into typed arrays. */
export async function loadSplat(url) {
  const buf = await (await fetch(url)).arrayBuffer();
  const head = new Uint8Array(buf);
  const marker = "\nend_header\n";
  let text = "";
  const limit = Math.min(head.length, 65536);
  for (let i = 0; i < limit; i++) text += String.fromCharCode(head[i]);
  const cut = text.indexOf(marker);
  if (cut < 0) throw new Error("not a PLY: no end_header");
  const headerText = text.slice(0, cut);
  const bodyStart = cut + marker.length;

  const count = Number((headerText.match(/element vertex\s+(\d+)/) || [])[1] || 0);
  const props = [...headerText.matchAll(/property\s+float\s+(\S+)/g)].map((m) => m[1]);
  if (!count || !props.length) throw new Error("PLY has no vertex element");

  const stride = props.length;
  const floats = new Float32Array(buf, bodyStart, count * stride);
  const off = {};
  props.forEach((p, i) => { off[p] = i; });
  for (const p of EXPECTED) {
    if (off[p] === undefined) throw new Error(`PLY missing property ${p}`);
  }

  const pos = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  const size = new Float32Array(count);
  const alpha = new Float32Array(count);
  const SH_C0 = 0.28209479177387814;
  for (let i = 0; i < count; i++) {
    const b = i * stride;
    pos[i * 3] = floats[b + off.x];
    pos[i * 3 + 1] = floats[b + off.y];
    pos[i * 3 + 2] = floats[b + off.z];
    for (let c = 0; c < 3; c++) {
      const dc = floats[b + off[`f_dc_${c}`]];
      col[i * 3 + c] = Math.min(1, Math.max(0, 0.5 + SH_C0 * dc));
    }
    size[i] = Math.exp(0.5 * (floats[b + off.scale_0] + floats[b + off.scale_1]));
    const op = floats[b + off.opacity];
    alpha[i] = 1 / (1 + Math.exp(-op));
  }
  return { count, pos, col, size, alpha };
}

/** Screen-space scale factor so a splat of radius r metres covers r on screen. */
export function splatScaleFor(camera, renderer) {
  const height = renderer.domElement.height || renderer.domElement.clientHeight;
  const fov = (camera.fov * Math.PI) / 180;
  return height / (2 * Math.tan(fov / 2));
}

const VERT = /* glsl */ `
  attribute vec3 aColor;
  attribute float aSize;
  attribute float aAlpha;
  uniform float uScale;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vColor = aColor;
    vAlpha = aAlpha;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    // a gaussian of radius r at depth d subtends uScale * r / d pixels
    gl_PointSize = clamp(uScale * aSize * 1.8 / max(-mv.z, 0.05), 1.0, 64.0);
    gl_Position = projectionMatrix * mv;
  }
`;

const FRAG = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec2 d = gl_PointCoord - vec2(0.5);
    float r = length(d) * 2.0;
    if (r > 1.0) discard;
    float a = vAlpha * smoothstep(1.0, 0.35, r);
    gl_FragColor = vec4(vColor, a);
  }
`;

export function createSplat(splat, { pixelRatio = 1 } = {}) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(splat.pos, 3));
  g.setAttribute("aColor", new THREE.BufferAttribute(splat.col, 3));
  g.setAttribute("aSize", new THREE.BufferAttribute(splat.size, 1));
  g.setAttribute("aAlpha", new THREE.BufferAttribute(splat.alpha, 1));
  g.computeBoundingSphere();

  const material = new THREE.ShaderMaterial({
    vertexShader: VERT,
    fragmentShader: FRAG,
    transparent: true,
    depthTest: true,
    depthWrite: false,
    uniforms: { uScale: { value: 300 * pixelRatio } },
  });

  const points = new THREE.Points(g, material);
  points.frustumCulled = true;
  points.name = "splat";
  return points;
}
