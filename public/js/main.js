/**
 * PANODROME — Stage 1 · main
 * Zero-Distortion Spatial Experience & Clean UI.
 *
 * Boot → intro → room lifecycle (pristine sphere, one doorway waypoint,
 * optical glide) → GSAP optical warp transitions.
 *
 * SILENT BY DESIGN: no audio engine is loaded in Stage 1
 * (real spatial audio arrives in Stage 3, built properly).
 */
import * as THREE from "three";
import { i18n } from "./i18n.js";
import { buildRoomSphere, prefetchRoom } from "./sphere.js";
import { OpticalControls } from "./controls.js";
import { Waypoint, projectToScreen } from "./portals.js";
import { HUD } from "./hud.js";

const state = {
  db: null,
  roomIdx: -1,
  room: null,
  meshObj: null,
  waypoint: null,
  started: false,
  transitioning: false,
};

let renderer, scene, camera, controls, hud;
const clock = new THREE.Clock();
const raycaster = new THREE.Raycaster();
const pointerNdc = new THREE.Vector2();
let hoveredWaypoint = false;
const isTouch = matchMedia("(pointer: coarse)").matches;

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
  camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.1, 1200);
  camera.rotation.order = "YXZ";

  hud = new HUD();

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

  controls = new OpticalControls(camera, renderer.domElement);
  controls.onClick = (x, y) => handleClick(x, y);
  controls.onDouble = (x, y) => handleDouble(x, y);
  hud.bindWalkPad(controls);

  hud.initIntro(state.db.rooms[0].preview, onEnter);
  hud.onLangToggle(() => {
    const next = i18n.lang === "en" ? "fa" : "en";
    localStorage.setItem("panodrome_lang", next);
    i18n.setLang(next);
    if (state.room) hud.setRoom(state.room, state.roomIdx, state.db.rooms.length);
  });
  hud.onViewButton(() => {
    if (controls.glided) {
      controls.resetView();          // "بازگشت به مرکز فضا"
    } else {
      toggleFullscreen();
    }
  });
  hud.onNavigate((dir) => {
    const n = state.db.rooms.length;
    navigateTo((state.roomIdx + dir + n) % n);
  });
  hud.onWaypointChip(() => state.waypoint && warpThrough(state.waypoint));

  renderer.domElement.addEventListener("pointermove", onPointerMove);
  addEventListener("resize", onResize);

  renderer.setAnimationLoop(tick);

  // test/debug hook (safe no-op in production)
  window.__panodrome = {
    state,
    camera,
    get controls() { return controls; },
    get hud() { return hud; },
    rooms: () => state.db.rooms,
    spherePurity: () => (state.meshObj ? state.meshObj.radiusDeviation : null),
    textureSize: () => (state.meshObj ? [state.meshObj.texture.image.width, state.meshObj.texture.image.height] : null),
    waypointScreen: () => {
      if (!state.waypoint) return null;
      const p = projectToScreen(state.waypoint.group.position, camera);
      return {
        ...p,
        dist: Math.round(camera.position.distanceTo(state.waypoint.group.position) * 100) / 100,
        target: state.waypoint.targetRoom.id,
        x: Math.round(p.x), y: Math.round(p.y),
      };
    },
    setGlide: (v) => controls.glideTo(v),
    resetView: () => controls.resetView(),
    warpNext: () => state.waypoint && warpThrough(state.waypoint),
    uiBounds: () => {
      const vw = innerWidth, vh = innerHeight;
      const ids = ["room-pill", "btn-lang", "btn-view", "nav-capsule", "walk-pad", "wp-chip", "btn-enter"];
      const out = [];
      for (const id of ids) {
        const el = document.getElementById(id);
        if (!el) continue;
        const cs = getComputedStyle(el);
        const hidden = el.classList.contains("hud-hidden") || cs.display === "none" || parseFloat(cs.opacity || "1") < 0.02;
        if (hidden) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) continue;
        out.push({
          id,
          rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
          inside: r.x >= 8 && r.y >= 8 && r.x + r.width <= vw - 8 && r.y + r.height <= vh - 8,
        });
      }
      return out;
    },
  };
}

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen?.();
  else document.documentElement.requestFullscreen?.();
}

async function onEnter() {
  if (state.started) return;
  state.started = true;
  hud.hideIntro();
  hud.showLoading(true);
  hud.setLoadProgress(0.1);
  await loadRoom(0);
  hud.setLoadProgress(1);
  hud.showLoading(false);
  hud.showHud();

  // cinematic settle-in: a soft wide→rest fov breath
  controls.enabled = false;
  controls.w = -0.6; controls.wTarget = 0; controls.wVel = 0;
  requestAnimationFrame(() => {
    controls.enabled = true;
    state._settleGuard = performance.now() + 1600;
  });
}

/* ------------------------------------------------------------- room lifecycle */

async function loadRoom(idx) {
  const room = state.db.rooms[idx];
  state.roomIdx = idx;
  state.room = room;

  if (state.meshObj) {
    scene.remove(state.meshObj.mesh);
    state.meshObj.dispose();
    state.meshObj = null;
  }
  if (state.waypoint) {
    scene.remove(state.waypoint.group);
    state.waypoint.dispose();
    state.waypoint = null;
  }
  hud.hideWaypointChip();

  hud.setLoadProgress(0.15);
  const meshObj = await buildRoomSphere(room, renderer);
  hud.setLoadProgress(0.85);
  state.meshObj = meshObj;
  scene.add(meshObj.mesh);

  // one verified doorway waypoint → next room in the curated sequence
  const n = state.db.rooms.length;
  const nextRoom = state.db.rooms[(idx + 1) % n];
  const wp = new Waypoint(room.portals[0], nextRoom);
  scene.add(wp.group);
  state.waypoint = wp;

  controls.setRoom(room);
  camera.fov = 70;
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  hud.setRoom(room, idx, n);

  hud.setLoadProgress(1);
  setTimeout(() => prefetchRoom(nextRoom), 1500);
}

/* ------------------------------------------------------------- optical warp */

function warpThrough(waypoint) {
  if (state.transitioning) return;
  const dir = waypoint.doorPos().sub(camera.position);
  navigateTo(state.db.rooms.indexOf(waypoint.targetRoom), dir);
}

function navigateTo(idx, dirWorld) {
  if (state.transitioning || idx === state.roomIdx) return;
  state.transitioning = true;
  controls.enabled = false;
  hud.hideWaypointChip();

  const dir = (dirWorld || new THREE.Vector3()).clone();
  dir.y = 0;
  if (dir.lengthSq() < 1e-6) camera.getWorldDirection(dir).setY(0);
  dir.normalize();

  const start = camera.position.clone();
  const end = start.clone().addScaledVector(dir, 0.18);   // micro-parallax lean-in

  const tl = gsap.timeline({
    onComplete: async () => {
      await loadRoom(idx);
      camera.fov = 70;
      camera.updateProjectionMatrix();
      // arrival breath: slightly wide fov springs back to rest
      controls.w = -0.55; controls.wTarget = 0; controls.wVel = 0;
      gsap.to("#fade", { opacity: 0, duration: 0.8, ease: "power2.out" });
      controls.enabled = true;
      state.transitioning = false;
    },
  });
  tl.to(camera.position, { x: end.x, y: start.y, z: end.z, duration: 0.9, ease: "power2.in" }, 0);
  tl.to(camera, { fov: 38, duration: 0.9, ease: "power2.in", onUpdate: () => camera.updateProjectionMatrix() }, 0);
  tl.to("#fade", { opacity: 1, duration: 0.48, ease: "power1.in" }, 0.42);
}

/* ------------------------------------------------------------- pointer logic */

function onPointerMove(e) {
  if (!state.started || state.transitioning || isTouch) return;
  const hit = raycastWaypoint(e.clientX, e.clientY);
  if (hit !== hoveredWaypoint) {
    hoveredWaypoint = hit;
    renderer.domElement.style.cursor = hit ? "pointer" : "";
    if (hit) {
      const p = projectToScreen(state.waypoint.group.position, camera);
      hud.showWaypointChip(state.waypoint.targetRoom, p.x, p.y);
    } else {
      hud.hideWaypointChip();
    }
  }
  if (hoveredWaypoint && state.waypoint) {
    const p = projectToScreen(state.waypoint.group.position, camera);
    hud.placeWaypointChip(p.x, p.y);
  }
}

function raycastWaypoint(px, py) {
  if (!state.waypoint) return false;
  pointerNdc.set((px / innerWidth) * 2 - 1, -(py / innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointerNdc, camera);
  return raycaster.intersectObject(state.waypoint.collider, false).length > 0;
}

function handleClick(x, y) {
  if (!state.started || state.transitioning) return;
  if (raycastWaypoint(x, y)) {
    // desktop: hover already previewed the chip — click travels.
    // touch: first tap previews, the second tap (ring or chip) travels.
    if (!isTouch || hud.chipOpen) warpThrough(state.waypoint);
    else {
      const p = projectToScreen(state.waypoint.group.position, camera);
      hud.showWaypointChip(state.waypoint.targetRoom, p.x, p.y);
    }
    return;
  }
  // tapping out: step back to the centre of the space
  hud.hideWaypointChip();
  if (controls.glided) {
    controls.resetView();
  }
}

function handleDouble(x, y) {
  if (!state.started || state.transitioning) return;
  if (raycastWaypoint(x, y)) { warpThrough(state.waypoint); return; }

  // turn toward the tapped point and glide in optically
  pointerNdc.set((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointerNdc, camera);
  let dir = null;
  if (state.meshObj) {
    const hit = raycaster.intersectObject(state.meshObj.mesh, false)[0];
    if (hit) dir = hit.point.clone().sub(camera.position).normalize();
  }
  if (!dir) camera.getWorldDirection((dir = new THREE.Vector3()));
  controls.lookToward(dir);
  controls.glideTo(0.85, dir);
}

/* ------------------------------------------------------------- loop */

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  const t = clock.elapsedTime;

  controls.update(dt);

  if (state.waypoint) {
    state.waypoint.update(t, dt, camera, hoveredWaypoint);
  }

  hud.setGlided(controls.glided);
  renderer.render(scene, camera);
}

function onResize() {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}
