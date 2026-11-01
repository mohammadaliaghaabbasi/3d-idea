/**
 * PANODROME — Spatial Engine v1 · main
 * Boot → intro → room lifecycle (load displaced mesh, portals, hotspots, audio)
 * → 6DoF loop → portal transitions with GSAP → routing modes.
 */
import * as THREE from "three";
import { i18n } from "./i18n.js";
import { AudioEngine } from "./audio.js";
import { buildRoomMesh, prefetchRoom } from "./panorama.js";
import { SixDofControls } from "./controls.js";
import { Portal, computeRoutes } from "./portals.js";
import { HUD } from "./hud.js";

/* ------------------------------------------------------------------ boot */
const state = {
  db: null,
  roomIdx: -1,
  room: null,
  meshObj: null,      // {mesh, dispose}
  portals: [],
  hotspots: [],
  mode: "architect",
  transitioning: false,
  started: false,
  portalCooldown: 0,
};

let renderer, scene, camera, controls, audio, hud;
const clock = new THREE.Clock();
const raycaster = new THREE.Raycaster();
const pointerNdc = new THREE.Vector2();
let hoveredPortal = null, hoveredHotspot = null;

main();

async function main() {
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  } catch (e) {
    document.getElementById("webgl-error").classList.remove("hud-hidden");
    return;
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(innerWidth, innerHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  document.getElementById("scene").appendChild(renderer.domElement);

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.05, 500);
  camera.rotation.order = "YXZ";

  audio = new AudioEngine();
  hud = new HUD();

  // restore language preference
  const saved = localStorage.getItem("panodrome_lang");
  i18n.setLang(saved === "fa" ? "fa" : "en");

  try {
    const res = await fetch("data/rooms_db.json");
    if (!res.ok) throw new Error("rooms_db " + res.status);
    state.db = await res.json();
  } catch (e) {
    hud.el.loadText.textContent = "Could not load data/rooms_db.json — serve public/ over HTTP.";
    hud.showLoading(true);
    return;
  }

  hud.initIntro(state.db.rooms[0].preview, onEnter);
  hud.onModeChange(setMode);
  hud.onLangToggle(() => {
    const next = i18n.lang === "en" ? "fa" : "en";
    localStorage.setItem("panodrome_lang", next);
    i18n.setLang(next);
    if (state.room) hud.setRoom(state.room, state.roomIdx, state.db.rooms.length);
    if (hoveredPortal) showPortalTooltip(hoveredPortal, lastPointer.x, lastPointer.y);
    if (hoveredHotspot) showHotspotTooltip(hoveredHotspot, lastPointer.x, lastPointer.y);
  });
  hud.onSoundToggle(() => {
    audio.setMuted(!audio.muted);
    hud.setSoundIcon(audio.muted);
  });
  hud.onHelpToggle(() => hud.toggleHelp());

  controls = new SixDofControls(camera, renderer.domElement);
  controls.onStep = () => {
    if (state.room) audio.step(state.room.audio.footsteps || state.room.floor_material);
  };
  controls.onClick = (x, y) => handleClick(x, y);
  hud.bindWalkPad(controls);

  renderer.domElement.addEventListener("pointermove", onPointerMove);
  addEventListener("resize", onResize);

  renderer.setAnimationLoop(tick);

  // tiny debug/test hook (safe no-op in production)
  window.__panodrome = {
    state,
    camera,
    portalScreen: () =>
      state.portals.map((p) => {
        const v = p.group.position.clone().project(camera);
        return {
          id: p.def.id,
          x: Math.round((v.x * 0.5 + 0.5) * innerWidth),
          y: Math.round((-v.y * 0.5 + 0.5) * innerHeight),
          behind: v.z > 1,
          target: p.target,
          reason: p.reason,
        };
      }),
  };
}

async function onEnter() {
  if (state.started) return;
  state.started = true;
  audio.init();
  audio.resume();
  hud.hideIntro();
  hud.showLoading(true);
  hud.setLoadProgress(0.05);
  await loadRoom(0);
  hud.setLoadProgress(1);
  hud.showLoading(false);
  hud.showHud();
  hud.setMode(state.mode);

  // cinematic settle-in
  const y0 = camera.position.y;
  camera.position.y += 0.35;
  camera.updateMatrixWorld();
  controls.enabled = false;
  gsap.to(camera.position, {
    y: y0, duration: 1.4, ease: "power3.out",
    onComplete: () => { controls.enabled = true; },
  });
}

/* ------------------------------------------------------------- room lifecycle */

async function loadRoom(idx) {
  const room = state.db.rooms[idx];
  state.roomIdx = idx;
  state.room = room;

  // teardown previous
  if (state.meshObj) {
    scene.remove(state.meshObj.mesh);
    state.meshObj.dispose();
    state.meshObj = null;
  }
  state.portals.forEach((p) => { scene.remove(p.group); p.dispose(); });
  state.portals = [];
  state.hotspots.forEach((h) => { scene.remove(h.sprite); h.sprite.material.map.dispose(); h.sprite.material.dispose(); });
  state.hotspots = [];

  hud.setLoadProgress(0.15);
  const meshObj = await buildRoomMesh(room);
  hud.setLoadProgress(0.85);
  state.meshObj = meshObj;
  scene.add(meshObj.mesh);

  // portals + routing targets
  const routes = computeRoutes(state.db.rooms, idx, state.mode);
  room.portals.forEach((def, i) => {
    const p = new Portal(def);
    p.target = routes.targets[i] !== undefined ? routes.targets[i] : routes.targets[0];
    p.reason = routes.reason;
    scene.add(p.group);
    state.portals.push(p);
  });

  // material inspector hotspots
  room.hotspots.forEach((def) => {
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: hotspotTexture(), transparent: true, depthTest: true })
    );
    sprite.position.fromArray(def.position);
    sprite.scale.setScalar(0.085);
    sprite.renderOrder = 5;
    scene.add(sprite);
    state.hotspots.push({ def, sprite, baseScale: 0.085 });
  });

  scene.updateMatrixWorld(true);

  // controls + audio + hud
  controls.setRoom(room);
  camera.fov = room.room_shape.width < 4.5 ? 74 : 70;
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  audio.setRoom(room.audio);
  hud.setRoom(room, idx, state.db.rooms.length);

  hud.setLoadProgress(1);
  state.portalCooldown = performance.now() + 1200;

  // prefetch likely next rooms
  setTimeout(() => routes.targets.forEach((t) => prefetchRoom(state.db.rooms[t])), 1800);
}

function setMode(mode) {
  state.mode = mode;
  hud.setMode(mode);
  if (!state.room) return;
  const routes = computeRoutes(state.db.rooms, state.roomIdx, mode);
  state.portals.forEach((p, i) => {
    p.target = routes.targets[i] !== undefined ? routes.targets[i] : routes.targets[0];
    p.reason = routes.reason;
  });
  routes.targets.forEach((t) => prefetchRoom(state.db.rooms[t]));
}

/* ------------------------------------------------------------- transitions */

async function transition(portal) {
  if (state.transitioning || !portal || portal.target === null) return;
  state.transitioning = true;
  controls.enabled = false;
  hud.hideTooltip();
  audio.portalWhoosh();

  const center = portal.planeCenterWorld();
  const overshoot = center.clone().addScaledVector(portal.normal, 0.35);

  const tl = gsap.timeline({
    onComplete: async () => {
      await loadRoom(portal.target);
      audio.chime();
      gsap.to("#fade", { opacity: 0, duration: 0.7, ease: "power2.out" });
      const y0 = camera.position.y;
      camera.position.y = y0 + 0.22;
      gsap.to(camera.position, {
        y: y0, duration: 1.1, ease: "power3.out",
        onComplete: () => {
          controls.enabled = true;
          state.transitioning = false;
        },
      });
    },
  });
  tl.to(camera.position, {
    x: overshoot.x, y: center.y, z: overshoot.z,
    duration: 0.9, ease: "power2.in",
  });
  tl.to("#fade", { opacity: 1, duration: 0.32, ease: "power1.in" }, "-=0.3");
}

/* ------------------------------------------------------------- pointer / raycast */

const lastPointer = { x: 0, y: 0 };

function onPointerMove(e) {
  lastPointer.x = e.clientX; lastPointer.y = e.clientY;
  if (!state.started || state.transitioning) return;
  const hit = raycast(e.clientX, e.clientY);

  const portal = hit?.portal ?? null;
  const hotspot = hit?.hotspot ?? null;

  if (portal !== hoveredPortal) {
    hoveredPortal = portal;
    renderer.domElement.style.cursor = portal ? "pointer" : "";
  }
  if (hotspot !== hoveredHotspot) {
    hoveredHotspot = hotspot;
    if (!portal) renderer.domElement.style.cursor = hotspot ? "help" : "";
  }

  if (portal) showPortalTooltip(portal, e.clientX, e.clientY);
  else if (hotspot) showHotspotTooltip(hotspot, e.clientX, e.clientY);
  else hud.hideTooltip();
}

function raycast(px, py) {
  pointerNdc.set((px / innerWidth) * 2 - 1, -(py / innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointerNdc, camera);
  const portalMeshes = state.portals.map((p) => p.membrane);
  const hits = raycaster.intersectObjects([...portalMeshes, ...state.hotspots.map((h) => h.sprite)], false);
  if (!hits.length) return null;
  const obj = hits[0].object;
  const pi = portalMeshes.indexOf(obj);
  if (pi >= 0) return { portal: state.portals[pi] };
  return { hotspot: state.hotspots.find((h) => h.sprite === obj) };
}

function handleClick(px, py) {
  if (!state.started || state.transitioning) return;
  const hit = raycast(px, py);
  if (hit?.portal) transition(hit.portal);
}

function showPortalTooltip(portal, x, y) {
  const t = i18n.t, L = i18n.lang;
  const target = state.db.rooms[portal.target];
  if (!target) return hud.hideTooltip();
  hud.showTooltip(
    x, y,
    `${t.portal_label}`,
    `<b>${target.name[L] || target.name.en}</b><br>${t.portal_to} · ${t.reason[portal.reason] || ""}`
  );
}

function showHotspotTooltip(hs, x, y) {
  const L = i18n.lang;
  const d = hs.def;
  hud.showTooltip(x, y, d.label[L] || d.label.en, d.note[L] || d.note.en, true);
}

/* ------------------------------------------------------------- loop */

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  const t = clock.elapsedTime;

  controls.update(dt);

  // portal animation + proximity trigger
  for (const p of state.portals) {
    p.update(t, p === hoveredPortal);
    if (
      controls.enabled && !state.transitioning &&
      performance.now() > state.portalCooldown &&
      p.contains(camera.position)
    ) {
      transition(p);
    }
  }

  // hotspot pulse
  for (const h of state.hotspots) {
    const pulse = 1 + 0.16 * Math.sin(t * 2.6 + h.def.position[0] * 7);
    const hover = h === hoveredHotspot ? 1.35 : 1;
    h.sprite.scale.setScalar(h.baseScale * pulse * hover);
  }

  renderer.render(scene, camera);
}

function onResize() {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}

/* ------------------------------------------------------------- helpers */

let _hotspotTex = null;
function hotspotTexture() {
  if (_hotspotTex) return _hotspotTex;
  const s = 64;
  const cv = document.createElement("canvas");
  cv.width = s; cv.height = s;
  const ctx = cv.getContext("2d");
  ctx.strokeStyle = "rgba(110,231,255,0.95)";
  ctx.lineWidth = 3.5;
  ctx.beginPath(); ctx.arc(s / 2, s / 2, s * 0.34, 0, Math.PI * 2); ctx.stroke();
  ctx.fillStyle = "rgba(238,242,248,0.9)";
  ctx.beginPath(); ctx.arc(s / 2, s / 2, s * 0.1, 0, Math.PI * 2); ctx.fill();
  _hotspotTex = new THREE.CanvasTexture(cv);
  _hotspotTex.colorSpace = THREE.SRGBColorSpace;
  return _hotspotTex;
}
