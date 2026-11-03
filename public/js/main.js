/**
 * PANODROME — Stage 1.5 · main
 * True First-Person Spatial Experience.
 *
 * Boot → intro → room lifecycle (true room volume + physics walking,
 * doorway waypoint with routing modes) → GSAP warp transitions.
 *
 * Stage 1.6.1 (owner emergency order 2026-11-02): the furniture GLB layer
 * and inpainted shells are PURGED (spike/smudge audit).  Rooms render as a
 * smooth RELIEF DOME (room.js) textured with the crisp original pano; real
 * physics colliders + glass floor halos stay (collider.js); walking is
 * bounded by the elastic radial envelope (controls.js).
 *
 * Stage 1.5 laws (locked 2026-11-02):
 *   · camera.fov is FIXED — 68° desktop / 75° touch. Walking is real
 *     position translation, never a focal-length zoom.
 *   · The room renders on a true metric room volume (room.js) — walls and
 *     floor stay perfectly flat and plumb, forever.
 *   · Walking is resolved against room_bounds + obstacle_colliders
 *     (collider.js) with sliding response — bump into the grand piano and
 *     you stop, then glide along it.
 *   · Walking physically into the doorway ring (< 1.1 m) travels to the
 *     next room by the active routing mode.
 *   · Audio is the warm acoustic engine (audio.js): soft low-passed
 *     footsteps every 0.65 m of real travel + gentle room air.
 */
import * as THREE from "three";
import { i18n } from "./i18n.js";
import { buildRoomVolume, prefetchRoom } from "./room.js";
import { WalkingControls } from "./controls.js";
import { WalkWorld, WalkFX } from "./collider.js";
import { Waypoint, computeRoutes, projectToScreen, WALK_IN_DIST } from "./portals.js";
import { AudioEngine } from "./audio.js";
import { HUD } from "./hud.js";

const FOV_DESKTOP = 68;      // FIXED — walking is translation, never zoom
const FOV_TOUCH = 75;        // FIXED

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
};

let renderer, scene, camera, controls, hud, audio;
const clock = new THREE.Clock();
const raycaster = new THREE.Raycaster();
const pointerNdc = new THREE.Vector2();
const floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
let hoveredWaypoint = false;
const isTouch = matchMedia("(pointer: coarse)").matches;
const FOV = isTouch ? FOV_TOUCH : FOV_DESKTOP;

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
  camera = new THREE.PerspectiveCamera(FOV, innerWidth / innerHeight, 0.05, 200);
  camera.rotation.order = "YXZ";

  hud = new HUD();
  audio = new AudioEngine();

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

  controls = new WalkingControls(camera, renderer.domElement);
  controls.onClick = (x, y) => handleClick(x, y);
  controls.onDouble = (x, y) => handleDouble(x, y);
  controls.onStep = (material) => audio.step(material);
  controls.onBump = (bump) => handleBump(bump);

  hud.bindJoystick((v) => { controls.joy.x = v.x; controls.joy.y = v.y; });
  hud.setMuted(audio.muted);
  audio.onMuteChange = (m) => hud.setMuted(m);
  hud.onSoundToggle(() => audio.setMuted(!audio.muted));

  hud.initIntro(state.db.rooms[0].preview, onEnter);
  hud.onLangToggle(() => {
    const next = i18n.lang === "en" ? "fa" : "en";
    localStorage.setItem("panodrome_lang", next);
    i18n.setLang(next);
    if (state.room) hud.setRoom(state.room, state.roomIdx, state.db.rooms.length);
  });
  hud.onViewButton(() => {
    if (controls.moved) {
      controls.resetView();          // "بازگشت به مرکز فضا"
    } else {
      toggleFullscreen();
    }
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

  renderer.domElement.addEventListener("pointermove", onPointerMove);
  addEventListener("resize", onResize);

  renderer.setAnimationLoop(tick);

  // test/debug hook (safe no-op in production)
  window.__panodrome = {
    state,
    camera,
    get controls() { return controls; },
    get hud() { return hud; },
    get world() { return state.world; },
    get audio() { return audio; },
    rooms: () => state.db.rooms,
    fov: () => camera.fov,
    fovMust: () => FOV,
    pos: () => [camera.position.x, camera.position.y, camera.position.z].map((v) => Math.round(v * 1000) / 1000),
    movedFromStart: () => Math.hypot(controls.pos.x - controls.start.x, controls.pos.z - controls.start.z),
    travelled: () => Math.round(controls.travelled * 100) / 100,
    roomStats: () => {
      if (!state.meshObj) return null;
      const s = { ...state.meshObj.stats };
      s.isDome = !!state.meshObj.isDome;
      s.textureUrl = state.room ? state.room.panorama : null;
      s.obstacles = state.room?.walk?.obstacles?.length ?? 0;
      s.envelope = controls.envelope ? controls.envelopeState() : null;
      s.halos = state.fx?.halos?.count ?? 0;
      return s;
    },
    envelope: () => controls.envelopeState(),
    halos: () => (state.fx && state.fx.halos ? state.fx.halos.count : 0),
    textureSize: () => (state.meshObj ? state.meshObj.stats.textureSize : null),
    waypointScreen: () => {
      if (!state.waypoint) return null;
      const p = projectToScreen(state.waypoint.group.position, camera);
      return {
        ...p,
        dist: Math.round(camera.position.distanceTo(state.waypoint.group.position) * 100) / 100,
        walkDist: Math.round(state.waypoint.playerDist(camera) * 100) / 100,
        target: state.waypoint.targetRoom.id,
        x: Math.round(p.x), y: Math.round(p.y),
      };
    },
    walkTo: (x, z) => controls.walkTo(new THREE.Vector3(x, 0, z)),
    setMode: (m) => { state.mode = m; hud.setMode(m); retargetWaypoint(); },
    resetView: () => controls.resetView(),
    warpNext: () => state.waypoint && warpThrough(state.waypoint),
    // deterministic room jump for E2E (nav-next clicks are swallowed mid-warp)
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
        "room-pill", "btn-sound", "btn-lang", "btn-view", "mode-bar",
        "mode-architect", "mode-style", "mode-room_type", "mode-random",
        "nav-capsule", "bump-toast", "joystick", "wp-chip", "btn-enter",
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

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen?.();
  else document.documentElement.requestFullscreen?.();
}

async function onEnter() {
  if (state.started) return;
  state.started = true;
  audio.unlock();                       // user gesture → warm acoustic engine
  hud.setMuted(audio.muted);
  hud.hideIntro();
  hud.showLoading(true);
  hud.setLoadProgress(0.1);
  await loadRoom(0);
  hud.setLoadProgress(1);
  hud.showLoading(false);
  hud.showHud();

  // a soft step in — the player arrives in the space
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

  // build FIRST — the swap below is atomic, so state.room / world / waypoint
  // can never disagree (no walking in the previous room's collision world)
  hud.setLoadProgress(0.15);
  const meshObj = await buildRoomVolume(room, renderer);
  hud.setLoadProgress(0.85);

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
  if (state.fx) {
    state.fx.dispose(scene);
    state.fx = null;
  }

  state.meshObj = meshObj;
  scene.add(meshObj.mesh);
  state.roomIdx = idx;
  state.room = room;

  // physics world + floor walk FX (+ glass obstacle halos)
  state.world = new WalkWorld(room);
  state.fx = new WalkFX(scene, room);
  controls.setWorld(state.world);
  controls.setRoom(room);
  // Stage 1.6.1: elastic radial walk envelope (+ door/obstacle channels)
  controls.setEnvelope(computeEnvelope(room));

  // one verified doorway waypoint → routed next room
  const { target } = routeFor(idx);
  const wp = new Waypoint(room.portals[0], state.db.rooms[target]);
  // dome-fit: keep the ring floating 0.30 m in front of the TRUE relief wall
  fitWaypointToDome(wp, room, meshObj);
  scene.add(wp.group);
  state.waypoint = wp;

  // FIXED FOV — never a zoom, never touched while walking
  camera.fov = FOV;
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  hud.setRoom(room, idx, state.db.rooms.length);
  state.walkInArmedAt = performance.now() + 700;   // walk-in trigger arming

  hud.setLoadProgress(1);
  setTimeout(() => prefetchRoom(state.db.rooms[target]), 1500);
}

/* --------------------------------------------------- Stage 1.6.1 helpers */

/**
 * Controlled metric walk envelope (owner spec): elastic radial boundary
 * around the capture centre (base r from the bake, 1.1-1.35 m) with smooth
 * cos² channels toward each doorway ring and each obstacle collider, so
 * walk-in portals and furniture bumps stay reachable inside the dome.
 */
function computeEnvelope(room) {
  const c = room.camera;
  const base = (room.walk && room.walk.envelope && room.walk.envelope.r) || 1.2;
  const channels = [];

  const p = room.portals && room.portals[0] && room.portals[0].position;
  if (p) {
    const dx = p[0] - c.x, dz = p[2] - c.z;
    const dist = Math.hypot(dx, dz);
    const reach = dist - 1.0;                    // player stops ≤ 1.0 m from ring
    if (reach > base + 0.05) {
      channels.push({ ang: Math.atan2(dz, dx), reach, half: THREE.MathUtils.degToRad(22) });
    }
  }
  for (const o of (room.walk && room.walk.obstacles) || []) {
    const dx = o.x - c.x, dz = o.z - c.z;
    const dist = Math.hypot(dx, dz) || 1e-6;
    const ux = dx / dist, uz = dz / dist;
    // directional extent: how far the collider surface lies along the
    // capture->centre ray (box = first face crossed; cyl = radius)
    const ext = o.type === "cylinder"
      ? (o.r || 0)
      : Math.min((o.hw || 0) / Math.max(Math.abs(ux), 1e-3),
                 (o.hd || 0) / Math.max(Math.abs(uz), 1e-3));
    const reach = dist - ext - 0.30 + 0.06;      // player reaches THROUGH to
    // the collider face (touch = dist-ext-playerR, +6cm so the bump event
    // genuinely fires and the halo is bumpable)
    if (reach > base + 0.05) {
      channels.push({ ang: Math.atan2(dz, dx), reach, half: THREE.MathUtils.degToRad(16) });
    }
  }
  return { cx: c.x, cz: c.z, r: base, channels };
}

/** Pull the doorway ring to 0.30 m in front of the relief-dome wall. */
function fitWaypointToDome(wp, room, meshObj) {
  if (!meshObj || !meshObj.wallDistAt) return;
  const c = room.camera;
  const p = room.portals[0].position;
  const dx = p[0] - c.x, dz = p[2] - c.z;
  const dist = Math.hypot(dx, dz);
  const theta = Math.atan2(dz, -dx);             // pano convention (shader)
  const wall = meshObj.wallDistAt(theta);
  if (!wall || !isFinite(wall)) return;
  const maxR = wall - 0.30;
  if (dist > maxR && maxR > 0.6) {
    const k = maxR / dist;
    wp.group.position.set(c.x + dx * k, p[1], c.z + dz * k);
  }
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
  controls.enabled = false;
  controls.walkTarget = null;
  controls.vel.set(0, 0);
  hud.hideWaypointChip();
  audio.warp();

  const dir = (dirWorld || new THREE.Vector3()).clone();
  dir.y = 0;
  if (dir.lengthSq() < 1e-6) camera.getWorldDirection(dir).setY(0);
  dir.normalize();

  // step INTO the doorway: tween controls.pos (the single position source —
  // camera follows it every frame, so the warp never fights the walk loop)
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
  if (state.fx && state.fx.halos && bump.ob) state.fx.halos.flash(bump.ob);  // glass halo flash
  // ripple at the obstacle's screen position
  const hitX = camera.position.x + bump.nx * 1.2;
  const hitZ = camera.position.z + bump.nz * 1.2;
  const p = projectToScreen(new THREE.Vector3(hitX, 1.0, hitZ), camera);
  if (!p.behind) hud.ripple(p.x, p.y);
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
  hud.hideWaypointChip();
}

function handleDouble(x, y) {
  if (!state.started || state.transitioning) return;
  if (raycastWaypoint(x, y)) { warpThrough(state.waypoint); return; }

  // walk TO the tapped floor point — a real walk across the room
  pointerNdc.set((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointerNdc, camera);
  const hit = new THREE.Vector3();
  if (raycaster.ray.intersectPlane(floorPlane, hit)) {
    // clamp the destination into the walkable area
    const b = state.world?.bounds;
    if (b) {
      hit.x = THREE.MathUtils.clamp(hit.x, b.minX, b.maxX);
      hit.z = THREE.MathUtils.clamp(hit.z, b.minZ, b.maxZ);
    }
    const dir = hit.clone().sub(camera.position).normalize();
    controls.lookToward(dir);
    controls.walkTo(hit);
  }
}

/* ------------------------------------------------------------- loop */

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  const t = clock.elapsedTime;

  controls.update(dt);

  if (state.fx) state.fx.update(dt, controls.pos, controls.speed);

  if (state.waypoint && !state.transitioning) {
    state.waypoint.update(t, dt, camera, hoveredWaypoint);

    // walk physically INTO the doorway → travel
    if (state.started && performance.now() > state.walkInArmedAt) {
      const d = state.waypoint.playerDist(camera);
      if (d < WALK_IN_DIST) {
        warpThrough(state.waypoint);
      }
    }
  }

  hud.setMoved(controls.moved);
  renderer.render(scene, camera);
}

function onResize() {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}
