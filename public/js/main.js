/**
 * PANODROME — Stage 2.1 · main (TRUE-WALK EVERYWHERE — owner order 2026-11-03)
 * ============================================================================
 * The FOV 72°↔52° zoom hack is DEAD.  Every one of the 11 rooms is a bespoke
 * True-3D Architectural Scene (skills/build_all_3d_rooms.py) with REAL
 * multi-metre 6DoF walking (camera.fov LOCKED 68° desktop / 75° touch) and
 * exact furniture collision.
 *
 * VIEW MODES (state.viewMode):
 *   walk      — default; WASD / joystick / scroll / double-tap glide the
 *               camera metres through the true-3D scene.
 *   photo     — 🌐 عکس ۳۶۰ اصلی: the pure unwarped 4K sphere from the
 *               optical capture station.  Any walk input crossfades (350 ms)
 *               back into the aligned 3D walk scene.
 *   dollhouse — 🏠 ماکت ۳بعدی: the roof lifts, the camera orbits above the
 *               room, the radar becomes the dimensioned floor plan; tapping
 *               the floor glides the player down into walk mode at that spot.
 *
 * Also new: 🎨 tap-to-switch architectural materials (materials.js) and the
 * 📐 live floorplan radar (radar.js).
 */
import * as THREE from "three";
import { i18n } from "./i18n.js";
import { buildRoomVolume, prefetchRoom } from "./room.js";
import { WalkingControls, FOV_BASE } from "./controls.js";
import { WalkWorld, WalkFX } from "./collider.js";
import { Waypoint, computeRoutes, projectToScreen, WALK_IN_DIST } from "./portals.js";
import { AudioEngine } from "./audio.js";
import { HUD } from "./hud.js";
import { Radar } from "./radar.js";
import { Dollhouse } from "./dollhouse.js";
import { paletteName } from "./materials.js";

const state = {
  db: null,
  roomIdx: -1,
  room: null,
  meshObj: null,
  waypoint: null,
  world: null,
  fx: null,
  started: false,
  transitioning: false,
  mode: "architect",
  walkInArmedAt: 0,
  viewMode: "walk",          // walk | photo | dollhouse
  photoSphere: null,         // attached pano sphere (hybrid rooms)
  env: null,                 // PMREM environment texture
  radarVisible: true,
  descentPending: null,
};

let renderer, scene, camera, controls, hud, audio, radar, dollhouse;
const clock = new THREE.Clock();
const raycaster = new THREE.Raycaster();
const pointerNdc = new THREE.Vector2();
const floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
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
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  document.getElementById("scene").appendChild(renderer.domElement);

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(FOV_BASE, innerWidth / innerHeight, 0.05, 1200);
  camera.rotation.order = "YXZ";

  hud = new HUD();
  audio = new AudioEngine();
  radar = new Radar(camera);

  const saved = localStorage.getItem("panodrome_lang");
  i18n.setLang(saved === "fa" ? "fa" : "en");
  i18n.onChange(() => {
    if (state.room) {
      hud.setRoom(state.room, state.roomIdx, state.db.rooms.length);
      hud.setViewMode(state.viewMode);
    }
  });

  try {
    const res = await fetch("data/rooms_db.json");
    if (!res.ok) throw new Error("rooms_db " + res.status);
    state.db = await res.json();
  } catch (e) {
    hud.el.loadText.textContent = "Could not load data/rooms_db.json — serve public/ over HTTP.";
    hud.showLoading(true);
    return;
  }

  controls = new WalkingControls(camera, renderer.domElement);
  controls.onClick = (x, y) => handleClick(x, y);
  controls.onDouble = (x, y) => handleDouble(x, y);
  controls.onStep = (material) => audio.step(material);
  controls.onBump = (bump) => handleBump(bump);
  controls.onWalkIntent = () => crossfadeToWalk();

  dollhouse = new Dollhouse(camera, renderer.domElement, {
    onTapFloor: (x, y) => dollhouseTapFloor(x, y),
  });

  hud.bindJoystick((v) => { controls.joy.x = v.x; controls.joy.y = v.y; });
  hud.setMuted(audio.muted);
  audio.onMuteChange = (m) => hud.setMuted(m);
  hud.onSoundToggle(() => audio.setMuted(!audio.muted));

  hud.initIntro(state.db.rooms[0].preview, onEnter);
  hud.onLangToggle(() => {
    const next = i18n.lang === "en" ? "fa" : "en";
    localStorage.setItem("panodrome_lang", next);
    i18n.setLang(next);
  });
  hud.onViewButton(() => {
    if (state.viewMode !== "walk") return;
    if (controls.moved) controls.resetView();          // "بازگشت به مرکز فضا"
    else toggleFullscreen();
  });
  hud.onNavigate((dir) => {
    const n = state.db.rooms.length;
    navigateTo((state.roomIdx + dir + n) % n);
  });
  hud.onModeChange((mode) => {
    if (mode === state.mode) return;
    state.mode = mode;
    hud.setMode(mode);
    retargetWaypoint();
  });
  hud.onWaypointChip(() => state.waypoint && warpThrough(state.waypoint));
  hud.onRadarToggle(() => {
    state.radarVisible = radar.toggleVisible();
    hud.el.btnRadar.classList.toggle("on", state.radarVisible);
  });
  hud.onDollhouseToggle(() => toggleDollhouse());
  hud.onPhotoToggle(() => togglePhoto());
  hud.el.btnRadar.classList.toggle("on", true);

  renderer.domElement.addEventListener("pointermove", onPointerMove);
  addEventListener("resize", onResize);

  renderer.setAnimationLoop(tick);

  window.__panodrome = makeTestApi();
}

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen?.();
  else document.documentElement.requestFullscreen?.();
}

async function onEnter() {
  if (state.started) return;
  state.started = true;
  audio.unlock();
  hud.setMuted(audio.muted);
  hud.hideIntro();
  hud.showLoading(true);
  hud.setLoadProgress(0.1);
  await loadRoom(0);
  hud.setLoadProgress(1);
  hud.showLoading(false);
  hud.showHud();
  hud.setViewMode("walk");
  controls.enabled = true;
}

/* ------------------------------------------------------------- room lifecycle */

function routeFor(idx) {
  return computeRoutes(state.db.rooms, idx, state.mode);
}

function retargetWaypoint() {
  if (!state.waypoint || state.roomIdx < 0) return;
  const { target } = routeFor(state.roomIdx);
  state.waypoint.retarget(state.db.rooms[target]);
  if (hoveredWaypoint) {
    const p = projectToScreen(state.waypoint.group.position, camera);
    hud.showWaypointChip(state.waypoint.targetRoom, p.x, p.y);
  }
  prefetchRoom(state.db.rooms[target]);
}

async function loadRoom(idx) {
  const room = state.db.rooms[idx];
  hud.hideWaypointChip();
  state.viewMode = "walk";               // every room opens in true-3D walk

  hud.setLoadProgress(0.15);
  const meshObj = await buildRoomVolume(room, renderer);
  hud.setLoadProgress(0.85);

  // detach the old environment
  if (state.env) { scene.environment = null; state.env.dispose?.(); state.env = null; }

  if (state.meshObj) {
    scene.remove(state.meshObj.mesh);
    state.meshObj.dispose();
    state.meshObj = null;
    state.photoSphere = null;
  }
  if (state.waypoint) {
    scene.remove(state.waypoint.group);
    state.waypoint.dispose();
    state.waypoint = null;
  }
  if (state.fx) {
    state.fx.dispose(scene);
    state.fx = null;
  }

  state.meshObj = meshObj;
  scene.add(meshObj.mesh);
  state.roomIdx = idx;
  state.room = room;

  // physics world + grounding FX
  state.world = new WalkWorld(room);
  state.fx = new WalkFX(scene, room);
  state.fx.setMode("walk");
  controls.setWorld(state.world);
  controls.setRoom(room);

  // one verified doorway waypoint → routed next room
  const { target } = routeFor(idx);
  const wp = new Waypoint(room.portals[0], state.db.rooms[target]);
  scene.add(wp.group);
  state.waypoint = wp;

  // FOV LAW: locked at 68 (desktop) / 75 (touch) in every room, every mode
  camera.fov = FOV_BASE;
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();

  // photo sphere + environment light attach when their loads land
  meshObj.panoReady.then((p) => {
    if (state.meshObj !== meshObj) return;         // room changed meanwhile
    state.photoSphere = p;
  });
  meshObj.envReady.then((env) => {
    if (state.meshObj !== meshObj) return;
    if (env) {
      state.env = env;
      scene.environment = env;
      state.meshObj.root?.traverse((o) => {
        if (o.isMesh && o.material && o.material.isMeshStandardMaterial) {
          o.material.envMapIntensity = 0.4;
        }
      });
    }
  });

  radar.setRoom(room, state.world);
  radar.setPlanMode(false);
  audio.setRoom(room.audio || { ambient: "room_tone", reverb: 0.25 });
  hud.setRoom(room, idx, state.db.rooms.length);
  hud.setViewMode("walk");
  state.walkInArmedAt = performance.now() + 700;

  hud.setLoadProgress(1);
  setTimeout(() => prefetchRoom(state.db.rooms[target]), 1500);
}

/* ------------------------------------------------------------- view modes */

/** 🌐 toggle: pure photo from the capture station ↔ true-3D walk. */
function togglePhoto() {
  if (state.viewMode === "dollhouse" || !state.room.panorama || state.transitioning) return;
  if (state.viewMode === "photo") {
    crossfadeToWalk();
  } else {
    setPhotoMode();
  }
}

function setViewMode(mode) {
  state.viewMode = mode;
  hud.setViewMode(mode);
  state.fx?.setMode(mode);
  radar.setPlanMode(mode === "dollhouse");
  if (mode === "photo") {
    controls.enterPhoto();
  } else {
    controls.exitPhoto();
  }
  // photo mode KEEPS look-drag enabled (the body stays pinned); walk input
  // is intercepted by controls and fires onWalkIntent instead.
  controls.enabled = (mode === "walk" || mode === "photo") && state.started && !state.transitioning;
}

/** 350 ms crossfade INTO the photo (sphere fades over the 3D scene). */
function fadePhotoSphere(toVisible, ms = 350) {
  const p = state.photoSphere;
  if (!p) return;
  const from = p.mesh.material.opacity;
  const mat = p.mesh.material;
  gsap.to({ t: from }, {
    t: toVisible ? 1 : 0, duration: ms / 1000, ease: "power2.inOut",
    onUpdate() {
      mat.opacity = this.targets()[0].t;
      p.mesh.visible = mat.opacity > 0.005;
    },
    onComplete() { p.mesh.visible = toVisible; },
  });
}

async function setPhotoMode() {
  if (!state.photoSphere) {
    // pano texture may still be in flight — wait for it (it's prefetched)
    if (!state.meshObj.panoReady) return;
    await state.meshObj.panoReady;
    if (state.viewMode !== "photo") return;       // changed while waiting
  }
  setViewMode("photo");
  fadePhotoSphere(true, 350);
  if (state.photoSphere) state.meshObj.mesh.visible = true;   // keep under, crossfade shows sphere on top
  hud.showBump(i18n.t.view_photo, 1400);
}

/** Walk intent arrived while in photo mode → 350 ms crossfade into 3D walk. */
function crossfadeToWalk() {
  if (state.viewMode !== "photo") return;
  setViewMode("walk");
  // resume at the capture station (what the photo shows), then walk on
  controls.pos.set(state.room.camera.x, 0, state.room.camera.z);
  controls.vel.set(0, 0);
  fadePhotoSphere(false, 350);
  hud.showBump(i18n.t.view_walk, 1400);
}

/* ------------------------------------------------------------- dollhouse */

function toggleDollhouse() {
  if (state.transitioning) return;
  if (state.viewMode === "dollhouse") {
    // exit without moving the player — glide down to the spawn
    dollhouse.exitQuick();
    state.descentPending = true;
    const px = state.room.camera.x, pz = state.room.camera.z;
    dollhouse._exitYaw = 0;
    dollhouse._alreadyQuick = true;
    finishDescent(px, pz, state.room.initial_view.facing * 2 * Math.PI);
  } else if (state.viewMode === "walk") {
    setViewMode("dollhouse");
    dollhouse.enter(state.meshObj, state.room, renderer, camera.position);
    hud.showBump(i18n.t.dollhouse_hint, 2200);
  }
}

/** Tap the dollhouse floor → glide the player down into walk mode there. */
function dollhouseTapFloor(sx, sy) {
  pointerNdc.set((sx / innerWidth) * 2 - 1, -(sy / innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointerNdc, camera);
  const hit = new THREE.Vector3();
  if (!raycaster.ray.intersectPlane(floorPlane, hit)) return;
  const b = state.world.bounds;
  hit.x = THREE.MathUtils.clamp(hit.x, b.minX, b.maxX);
  hit.z = THREE.MathUtils.clamp(hit.z, b.minZ, b.maxZ);
  // land facing the room centre (feels deliberate)
  const yaw = Math.atan2(-(0 - hit.x), -(0 - hit.z));
  dollhouse._exitYaw = yaw;
  setViewModePending();
  dollhouse.exitTo(hit.x, hit.z, (x, z, y) => finishDescent(x, z, y));
}

function setViewModePending() {
  state.descentPending = true;         // tick must not fight the descent tween
  state.viewMode = "walk";       // input routing switches immediately
  hud.setViewMode("walk");
  state.fx?.setMode("walk");
  radar.setPlanMode(false);
}

function finishDescent(x, z, yaw) {
  state.descentPending = false;
  controls.pos.set(x, 0, z);
  controls.yaw = yaw || 0;
  controls.pitch = 0;
  controls.exitPhoto();
  state.viewMode = "walk";
  hud.setViewMode("walk");
  state.fx?.setMode("walk");
  radar.setPlanMode(false);
  controls.enabled = !state.transitioning;
}

/* ------------------------------------------------------------- warp */

function warpThrough(waypoint) {
  if (state.transitioning) return;
  const dir = waypoint.doorPos().sub(camera.position);
  navigateTo(state.db.rooms.indexOf(waypoint.targetRoom), dir);
}

function navigateTo(idx, dirWorld) {
  if (state.transitioning || idx === state.roomIdx) return;
  state.transitioning = true;
  if (state.viewMode === "dollhouse") dollhouse.exitQuick();
  controls.enabled = false;
  controls.walkTarget = null;
  controls.vel.set(0, 0);
  hud.hideWaypointChip();
  audio.warp();

  const dir = (dirWorld || new THREE.Vector3()).clone();
  dir.y = 0;
  if (dir.lengthSq() < 1e-6) camera.getWorldDirection(dir).setY(0);
  dir.normalize();

  // step INTO the doorway — the camera strides with the body (true 6DoF)
  const start = controls.pos.clone();
  const end = start.clone().addScaledVector(dir, 0.55);

  const tl = gsap.timeline({
    onComplete: async () => {
      await loadRoom(idx);
      gsap.to("#fade", { opacity: 0, duration: 0.8, ease: "power2.out" });
      controls.enabled = true;
      state.transitioning = false;
    },
  });
  tl.to(controls.pos, { x: end.x, z: end.z, duration: 0.55, ease: "power2.in" }, 0);
  tl.to("#fade", { opacity: 1, duration: 0.4, ease: "power1.in" }, 0.15);
}

/* ------------------------------------------------------------- collisions */

function handleBump(bump) {
  if (!bump) return;
  const label = bump.label[i18n.lang] || bump.label.en;
  hud.showBump(`${i18n.t.bump_prefix} ${label}`);
  audio.bump();
  const hitX = camera.position.x + bump.nx * 1.2;
  const hitZ = camera.position.z + bump.nz * 1.2;
  const p = projectToScreen(new THREE.Vector3(hitX, 1.0, hitZ), camera);
  if (!p.behind) hud.ripple(p.x, p.y);
}

/* ------------------------------------------------------------- pointer logic */

function onPointerMove(e) {
  if (!state.started || state.transitioning || isTouch || state.viewMode !== "walk") return;
  const hit = raycastWaypoint(e.clientX, e.clientY);
  const cursor = hit ? "pointer" : "";
  renderer.domElement.style.cursor = cursor;
  if (hit !== hoveredWaypoint) {
    hoveredWaypoint = hit;
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

/** Raycast the true-3D room meshes → the tapped mesh (or null). */
function raycastRoom(px, py) {
  if (!state.meshObj || !state.meshObj.root) return null;
  pointerNdc.set((px / innerWidth) * 2 - 1, -(py / innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointerNdc, camera);
  const hits = raycaster.intersectObject(state.meshObj.root, true);
  for (const h of hits) {
    if (h.object.isMesh && h.object.name && !h.object.name.startsWith("panodrome")) return h.object;
  }
  return null;
}

function handleClick(x, y) {
  if (!state.started || state.transitioning) return;
  if (raycastWaypoint(x, y)) {
    if (!isTouch || hud.chipOpen) warpThrough(state.waypoint);
    else {
      const p = projectToScreen(state.waypoint.group.position, camera);
      hud.showWaypointChip(state.waypoint.targetRoom, p.x, p.y);
    }
    return;
  }
  hud.hideWaypointChip();

  // 🎨 tap-to-switch architectural materials (walk + dollhouse modes)
  if (state.viewMode === "walk" || state.viewMode === "dollhouse") {
    const mesh = raycastRoom(x, y);
    if (mesh) {
      const kind = mesh.name.startsWith("floor") ? "floor"
        : mesh.name.startsWith("wall") ? "wall" : "furn";
      cycleMaterial(kind);
      const p = projectToScreen(new THREE.Vector3(mesh.position.x, 1.2, mesh.position.z), camera);
      if (!p.behind) hud.ripple(p.x, p.y);
      return;
    }
  }
}

async function cycleMaterial(kind) {
  const surfaces = state.meshObj?.surfaces;
  if (!surfaces || !state.room.mats) return;
  const key = await surfaces.cycle(kind, state.room.mats);
  if (key) {
    hud.showBump(`${i18n.t.mat_prefix} ${paletteName(key)}`, 1900);
  }
}

function handleDouble(x, y) {
  if (!state.started || state.transitioning) return;
  if (raycastWaypoint(x, y)) { warpThrough(state.waypoint); return; }

  if (state.viewMode === "photo") { crossfadeToWalk(); return; }
  if (state.viewMode !== "walk") return;

  // walk TO the tapped floor point — the footstep target ring marks it
  pointerNdc.set((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointerNdc, camera);
  const hit = new THREE.Vector3();
  if (raycaster.ray.intersectPlane(floorPlane, hit)) {
    const b = state.world?.bounds;
    if (b) {
      hit.x = THREE.MathUtils.clamp(hit.x, b.minX, b.maxX);
      hit.z = THREE.MathUtils.clamp(hit.z, b.minZ, b.maxZ);
    }
    const dir = hit.clone().sub(camera.position).normalize();
    controls.lookToward(dir);
    controls.walkTo(hit);
    state.fx.showTarget(hit);
  }
}

/* ------------------------------------------------------------- loop */

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  const t = clock.elapsedTime;
  try {
    if (state.viewMode !== "dollhouse" && !state.descentPending) {
      controls.update(dt);
      if (state.fx) {
        state.fx.update(dt, controls.effectivePos(), camera.position, controls.speed);
      }
    }

    if (state.waypoint && !state.transitioning) {
      state.waypoint.update(t, dt, camera, hoveredWaypoint);
      if (state.viewMode === "walk" && state.started && performance.now() > state.walkInArmedAt) {
        const d = state.waypoint.playerDist(controls.effectivePos());
        if (d < WALK_IN_DIST) warpThrough(state.waypoint);
      }
    }

    if (state.started) {
      radar.update(dt, controls.effectivePos(), controls.yaw);
    }
    hud.setMoved(controls.moved && state.viewMode === "walk");
    renderer.render(scene, camera);
    state.framesRendered = (state.framesRendered || 0) + 1;
    if (state.framesRendered % 45 === 0) {
      try {
        const cv = renderer.domElement;
        const url = cv.toDataURL("image/jpeg", 0.4);
        window.__rb = { len: url.length, head: url.slice(0, 40) };
        // tiny brightness probe: draw into a 2d canvas via an Image
        const im = new Image();
        im.onload = () => {
          const c2 = document.createElement("canvas");
          c2.width = 32; c2.height = 20;
          const x2 = c2.getContext("2d");
          x2.drawImage(im, 0, 0, 32, 20);
          const d = x2.getImageData(0, 0, 32, 20).data;
          let s = 0;
          for (let i = 0; i < d.length; i += 4) s += (d[i] + d[i + 1] + d[i + 2]) / 3;
          window.__rbMean = Math.round(s / (d.length / 4));
        };
        im.src = url;
      } catch (e) { window.__rb = String(e); }
    }
  } catch (err) {
    if (!window.__tickErrLogged) {
      window.__tickErrLogged = err && err.stack ? String(err.stack).slice(0, 600) : String(err);
      console.error("TICK ERROR:", err);
    }
    window.__tickErrCount = (window.__tickErrCount || 0) + 1;
  }
}

function onResize() {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}

/* ------------------------------------------------------------- E2E API */

function makeTestApi() {
  return {
    state,
    camera,
    get scene() { return scene; },
    get renderer() { return renderer; },
    get controls() { return controls; },
    get hud() { return hud; },
    get radar() { return radar; },
    get dollhouse() { return dollhouse; },
    get world() { return state.world; },
    get audio() { return audio; },
    rooms: () => state.db.rooms,
    fov: () => Math.round(camera.fov * 100) / 100,
    info: () => ({ ...renderer.info.render, memory: { ...renderer.info.memory } }),
    fovMust: () => FOV_BASE,
    fovStats: () => ({
      cur: Math.round(camera.fov * 100) / 100,
      base: FOV_BASE,
      minSeen: Math.round(controls.minFovSeen * 100) / 100,
      maxSeen: Math.round(controls.maxFovSeen * 100) / 100,
    }),
    viewMode: () => state.viewMode,
    setViewMode: (m) => {
      if (m === "photo") setPhotoMode();
      else if (m === "dollhouse") { if (state.viewMode !== "dollhouse") toggleDollhouse(); }
      else if (m === "walk") { if (state.viewMode === "photo") crossfadeToWalk(); else if (state.viewMode === "dollhouse") toggleDollhouse(); }
    },
    enterDollhouse: () => { if (state.viewMode !== "dollhouse") toggleDollhouse(); return state.viewMode; },
    exitDollhouseAt: (x, z) => {
      if (state.viewMode !== "dollhouse") return "not-in-dollhouse";
      dollhouse._exitYaw = 0;
      setViewModePending();
      dollhouse.exitTo(x, z, (px, pz, yaw) => finishDescent(px, pz, yaw));
      return "descending";
    },
    dollhouseLift: () => {
      const list = [];
      state.meshObj?.mesh.traverse((o) => {
        if (o.isMesh && (o.name.startsWith("ceiling") || o.name.startsWith("roof"))) {
          list.push({ name: o.name, y: +o.position.y.toFixed(3), op: o.material.opacity });
        }
      });
      return list;
    },
    mode: () => "free",
    pos: () => [camera.position.x, camera.position.y, camera.position.z].map((v) => Math.round(v * 1000) / 1000),
    virtualPos: () => [controls.pos.x, controls.pos.z].map((v) => Math.round(v * 1000) / 1000),
    travelled: () => Math.round(controls.travelled * 100) / 100,
    maxDisp: () => Math.round(controls.maxDisp * 100) / 100,
    movedFromStart: () => Math.hypot(controls.pos.x - controls.start.x, controls.pos.z - controls.start.z),
    offsetFromOrigin: () => Math.round(controls.cameraOffset() * 10000) / 10000,
    landingDone: () => !state.descentPending,
    setHudVisible: (v) => {
      document.body.classList.toggle("qa-hidden", !v);
      if (state.waypoint) state.waypoint.group.visible = v;   // the ring is UI, not the photo
      return v;
    },
    distanceTo: (x, z) => Math.hypot(controls.pos.x - x, controls.pos.z - z),
    maxOffsetSeen: () => Math.round(controls.maxOffsetSeen * 10000) / 10000,
    roomStats: () => {
      if (!state.meshObj) return null;
      const s = { ...state.meshObj.stats };
      s.kind = state.meshObj.kind;
      s.textureUrl = state.room ? (state.room.panorama || state.room.glb) : null;
      s.obstacles = state.room?.walk?.obstacles?.length ?? 0;
      s.sphereReady = !!state.photoSphere;
      s.envReady = !!state.env;
      return s;
    },
    sphereStats: () => state.photoSphere ? state.photoSphere.stats : null,
    mats: () => state.meshObj?.surfaces ? state.meshObj.surfaces.state() : null,
    tapMaterial: async (kind) => {
      await cycleMaterial(kind);
      return state.meshObj?.surfaces?.state()?.[kind]?.key || null;
    },
    radarVisible: () => state.radarVisible,
    radarPixels: () => {
      const cv = document.getElementById("radar");
      if (!cv) return 0;
      const ctx = cv.getContext("2d");
      const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
      let n = 0;
      for (let i = 3; i < d.length; i += 4) { if (d[i] > 8) n++; }
      return n;
    },
    walkTo: (x, z) => {
      const t = new THREE.Vector3(x, 0, z);
      const used = controls.walkTo(t) || t;
      state.fx?.showTarget(used);
      return used;
    },
    setMode: (m) => { state.mode = m; hud.setMode(m); retargetWaypoint(); },
    resetView: () => controls.resetView(),
    warpNext: () => state.waypoint && warpThrough(state.waypoint),
    gotoRoom: async (id) => {
      const i = state.db.rooms.findIndex((r) => r.id === id);
      if (i < 0 || i === state.roomIdx) return state.room?.id ?? null;
      if (state.transitioning) { await new Promise((r) => setTimeout(r, 300)); }
      await navigateTo(i);
      for (let k = 0; k < 60 && state.transitioning; k++) {
        await new Promise((r) => setTimeout(r, 100));
      }
      return state.room?.id ?? null;
    },
    uiBounds: () => {
      const vw = innerWidth, vh = innerHeight;
      const ids = [
        "room-pill", "room-badge", "btn-sound", "btn-lang", "btn-view",
        "btn-radar", "btn-dollhouse", "btn-photo", "mode-bar",
        "mode-architect", "mode-style", "mode-room_type", "mode-random",
        "nav-capsule", "bump-toast", "joystick", "wp-chip", "btn-enter",
        "radar-wrap", "view-pill",
      ];
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
