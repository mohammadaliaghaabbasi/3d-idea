/**
 * PANODROME — Spatial Engine v1.5 · main
 * Boot → intro → room lifecycle (displaced mesh, sleek portals, X-Ray pins,
 * moodboard, upload studio, commerce, narrator) → 6DoF loop → transitions.
 *
 * Walking: WASD · scroll · double-tap glide · mobile rocker · portal walk-in.
 */
import * as THREE from "three";
import { i18n } from "./i18n.js";
import { AudioEngine } from "./audio.js";
import { buildRoomMesh, prefetchRoom } from "./panorama.js";
import { SixDofControls } from "./controls.js";
import { Portal, PortalCard, computeRoutes } from "./portals.js";
import { HUD } from "./hud.js";
import { XRayLayer } from "./hotspots.js";
import { Moodboard } from "./moodboard.js";
import { Narrator } from "./narrator.js";
import { Commerce } from "./commerce.js";
import { UploadStudio } from "./upload_studio.js";

/* ------------------------------------------------------------------ boot */
const state = {
  db: null,
  roomIdx: -1,
  room: null,
  meshObj: null,      // {mesh, dispose}
  portals: [],
  mode: "architect",
  transitioning: false,
  started: false,
  portalCooldown: 0,
};

let renderer, scene, camera, controls, audio, hud, xray, moodboard, narrator, commerce, uploads, portalCard;
const clock = new THREE.Clock();
const raycaster = new THREE.Raycaster();
const pointerNdc = new THREE.Vector2();
let hoveredPortal = null, hoveredHotspot = null;
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
  camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.05, 500);
  camera.rotation.order = "YXZ";

  audio = new AudioEngine();
  hud = new HUD();
  xray = new XRayLayer(scene);
  narrator = new Narrator();
  commerce = new Commerce();
  portalCard = new PortalCard((p) => transition(p));

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

  // user-uploaded rooms (IndexedDB) join the routing pool
  uploads = new UploadStudio({
    onRoomCreated: (room) => {
      state.db.rooms.push(room);
      refreshRoutes();
      const idx = state.db.rooms.length - 1;
      loadRoom(idx);
    },
  });
  const persisted = await uploads.loadPersisted();
  persisted.forEach((room) => state.db.rooms.push(room));

  moodboard = new Moodboard({
    getRooms: () => (state.db ? state.db.rooms : []),
    onRoutesChanged: () => {
      refreshRoutes();
      hud.setMode(state.mode); // restore the mode-bar hint after tour changes
    },
    onGotoRoom: (idx) => { if (idx >= 0) loadRoom(idx); },
  });

  hud.initIntro(state.db.rooms[moodboard.entryIndex(state.db.rooms)].preview, onEnter);
  hud.onModeChange(setMode);
  hud.onLangToggle(() => {
    const next = i18n.lang === "en" ? "fa" : "en";
    localStorage.setItem("panodrome_lang", next);
    i18n.setLang(next);
    if (state.room) hud.setRoom(state.room, state.roomIdx, state.db.rooms.length);
    if (hoveredHotspot) showHotspotTooltip(hoveredHotspot, lastPointer.x, lastPointer.y);
  });
  hud.onSoundToggle(() => {
    audio.unlock();
    audio.setMuted(!audio.muted);
    hud.setSoundIcon(audio.muted);
  });
  hud.onHelpToggle(() => hud.toggleHelp());

  // narrator + lead-gen from the creator card
  hud.el.btnListen.addEventListener("click", () => {
    if (!state.room) return;
    const L = i18n.lang;
    narrator.speak(
      `${state.room.name[L] || state.room.name.en}. ${state.room.description[L] || state.room.description.en}`
    );
  });
  hud.el.btnHire.addEventListener("click", () => {
    if (state.room) commerce.openInquiry("design", state.room);
  });

  controls = new SixDofControls(camera, renderer.domElement);
  controls.onStep = () => {
    if (state.room) audio.step(state.room.audio.footsteps || state.room.floor_material);
  };
  controls.onClick = (x, y) => handleClick(x, y);
  controls.onDouble = (x, y) => handleDouble(x, y);
  hud.bindWalkRocker(controls);

  // X-Ray commerce + narrator hooks
  xray.onInquire = (def) => commerce.openInquiry("product", state.room, def);
  xray.onNarrate = (def) => {
    const L = i18n.lang;
    narrator.speak(`${def.title?.[L] || def.title?.en || ""}. ${def.desc?.[L] || def.desc?.en || ""}`);
  };
  narrator.onStateChange = (speaking) => {
    hud.el.btnListenLabel.textContent = speaking ? i18n.t.stop_listen : i18n.t.listen;
    xray.el.listen.title = speaking ? i18n.t.stop_listen : i18n.t.listen;
  };

  // robust audio unlock on ANY first gesture
  const unlock = () => audio.unlock();
  window.addEventListener("pointerdown", unlock, { once: false });
  window.addEventListener("touchstart", unlock, { passive: true });
  window.addEventListener("wheel", unlock, { passive: true });
  window.addEventListener("keydown", unlock);

  renderer.domElement.addEventListener("pointermove", onPointerMove);
  addEventListener("resize", onResize);

  renderer.setAnimationLoop(tick);

  // tiny debug/test hook (safe no-op in production)
  window.__panodrome = {
    state,
    camera,
    get controls() { return controls; },
    get xray() { return xray; },
    get moodboard() { return moodboard; },
    get commerce() { return commerce; },
    get narrator() { return narrator; },
    get uploads() { return uploads; },
    get portalCard() { return portalCard; },
    hotspotScreen: () =>
      (xray ? xray.pins : []).map((p) => {
        const v = p.sprite.position.clone().project(camera);
        return {
          id: p.def.id,
          cat: p.def.material_category,
          title: p.def.title?.en || p.def.label?.en || "",
          x: Math.round((v.x * 0.5 + 0.5) * innerWidth),
          y: Math.round((-v.y * 0.5 + 0.5) * innerHeight),
          behind: v.z > 1,
          visible: p.sprite.visible,
        };
      }),
    portalScreen: () =>
      state.portals.map((p) => {
        const v = p.group.position.clone().project(camera);
        return {
          id: p.def.id,
          fraction: p.def.fraction,
          sponsored: !!p.def.sponsored,
          x: Math.round((v.x * 0.5 + 0.5) * innerWidth),
          y: Math.round((-v.y * 0.5 + 0.5) * innerHeight),
          behind: v.z > 1,
          target: p.target,
          reason: p.reason,
          dist: Math.round(camera.position.distanceTo(p.group.position) * 10) / 10,
        };
      }),
    camPos: () => ({
      x: Math.round(camera.position.x * 100) / 100,
      y: Math.round(camera.position.y * 100) / 100,
      z: Math.round(camera.position.z * 100) / 100,
    }),
  };
}

async function onEnter() {
  if (state.started) return;
  state.started = true;
  audio.unlock();
  hud.hideIntro();
  hud.showLoading(true);
  hud.setLoadProgress(0.05);
  await loadRoom(moodboard.entryIndex(state.db.rooms));
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

  narrator.stop();
  portalCard.hide();

  // teardown previous
  if (state.meshObj) {
    scene.remove(state.meshObj.mesh);
    state.meshObj.dispose();
    state.meshObj = null;
  }
  state.portals.forEach((p) => { scene.remove(p.group); p.dispose(); });
  state.portals = [];
  xray.loadRoom(room);

  hud.setLoadProgress(0.15);
  const meshObj = await buildRoomMesh(room);
  hud.setLoadProgress(0.85);
  state.meshObj = meshObj;
  scene.add(meshObj.mesh);
  scene.updateMatrixWorld(true);

  // portals + routing targets (Dream House tour overrides the mode)
  const routes = currentRoutes();
  room.portals.forEach((def, i) => {
    const p = new Portal(def, camera);
    p.target = routes.targets[i] !== undefined ? routes.targets[i] : routes.targets[0];
    p.reason = routes.reason;
    p.anchorOnMesh(meshObj.mesh, room.camera, def.fraction % 1.0);
    scene.add(p.group);
    state.portals.push(p);
  });

  // controls + audio + hud
  controls.setRoom(room);
  camera.fov = room.room_shape.width < 4.5 ? 74 : 70;
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  audio.setRoom(room.audio);
  hud.setRoom(room, idx, state.db.rooms.length);
  hud.setMode(state.mode); // re-applies the mode hint
  moodboard.onRoomChanged(room, idx); // may override hint during a Dream-House tour

  hud.setLoadProgress(1);
  state.portalCooldown = performance.now() + 1100;

  // prefetch likely next rooms (data-URL rooms prefetch instantly)
  setTimeout(() => routes.targets.forEach((t) => prefetchRoom(state.db.rooms[t])), 1800);
}

function setMode(mode) {
  state.mode = mode;
  hud.setMode(mode);
  if (!state.room) return;
  if (moodboard.tourActive()) return; // Dream-House tour owns the routing
  refreshRoutes();
}

/** Current routing table — Dream House tour overrides the chosen mode. */
function currentRoutes() {
  if (!state.room) return computeRoutes(state.db.rooms, Math.max(state.roomIdx, 0), state.mode);
  if (moodboard && moodboard.tourActive()) {
    return moodboard.houseRoutes(state.db.rooms, state.roomIdx) ||
      computeRoutes(state.db.rooms, state.roomIdx, state.mode);
  }
  return computeRoutes(state.db.rooms, state.roomIdx, state.mode);
}

function refreshRoutes() {
  if (!state.room) return;
  const routes = currentRoutes();
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
  portalCard.hide();
  hud.hideTooltip();
  xray.closeCard(true);
  narrator.stop();
  audio.portalWhoosh();
  audio.walkSteps(4, state.room?.audio?.footsteps || "concrete", 0.26);

  const center = portal.group.position.clone();
  const overshoot = center.clone().addScaledVector(portal.normal || new THREE.Vector3(0, 0, 1), -0.45);

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
    duration: 0.85, ease: "power2.in",
  });
  tl.to("#fade", { opacity: 1, duration: 0.3, ease: "power1.in" }, "-=0.28");
}

/* ------------------------------------------------------------- pointer / raycast */

const lastPointer = { x: 0, y: 0 };

function onPointerMove(e) {
  lastPointer.x = e.clientX; lastPointer.y = e.clientY;
  if (!state.started || state.transitioning || isTouch) return;
  const hit = raycast(e.clientX, e.clientY);

  const portal = hit?.portal ?? null;
  const hotspot = hit?.hotspot ?? null;

  if (portal !== hoveredPortal) {
    hoveredPortal = portal;
    renderer.domElement.style.cursor = portal ? "pointer" : "";
    if (portal) {
      const target = state.db.rooms[portal.target];
      if (target) portalCard.show(portal, target);
    } else if (!portalCard._keepOpen) {
      portalCard.hide();
    }
  }
  if (hotspot !== hoveredHotspot) {
    hoveredHotspot = hotspot;
    if (!portal) renderer.domElement.style.cursor = hotspot ? "help" : "";
  }
  xray.setHover(hotspot);

  if (hotspot && !portal) showHotspotTooltip(hotspot, e.clientX, e.clientY);
  else if (!portal) hud.hideTooltip();
}

function raycast(px, py) {
  pointerNdc.set((px / innerWidth) * 2 - 1, -(py / innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointerNdc, camera);
  const portalMeshes = state.portals.flatMap((p) => p.colliderMeshes());
  const hits = raycaster.intersectObjects([...portalMeshes, ...xray.pinMeshes()], false);
  if (!hits.length) return null;
  const obj = hits[0].object;
  const pi = portalMeshes.indexOf(obj);
  if (pi >= 0) return { portal: state.portals[pi] };
  return { hotspot: xray.pins.find((p) => p.sprite === obj) };
}

function handleClick(px, py) {
  if (!state.started || state.transitioning) return;
  const hit = raycast(px, py);
  if (hit?.hotspot) { xray.openCard(hit.hotspot.def); return; }
  if (hit?.portal) {
    // first tap shows the room card; the card button (or a second quick tap)
    // travels — plus walking into the doorway always works
    if (portalCard.open && portalCard.portal === hit.portal) {
      transition(hit.portal);
    } else {
      const target = state.db.rooms[hit.portal.target];
      if (target) portalCard.show(hit.portal, target);
    }
  }
}

function handleDouble(px, py) {
  if (!state.started || state.transitioning) return;
  const hit = raycast(px, py);
  if (hit?.portal) { transition(hit.portal); return; }
  if (hit?.hotspot) { xray.openCard(hit.hotspot.def); return; }
  // walk toward the tapped point in the room (floor/furniture direction)
  pointerNdc.set((px / innerWidth) * 2 - 1, -(py / innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointerNdc, camera);
  let dir = null;
  if (state.meshObj) {
    const hit3 = raycaster.intersectObject(state.meshObj.mesh, false)[0];
    if (hit3) dir = hit3.point.clone().sub(camera.position);
  }
  if (!dir) {
    dir = new THREE.Vector3();
    camera.getWorldDirection(dir);
  }
  dir.y = 0;
  if (dir.lengthSq() < 0.01) return;
  controls.glide(dir.x, dir.z, 1.5 + Math.random() * 0.6);
}

function showHotspotTooltip(hs, x, y) {
  const L = i18n.lang;
  const d = hs.def;
  const title = d.title?.[L] || d.title?.en || d.label?.[L] || d.label?.en || "";
  const body = d.desc?.[L] || d.desc?.en || d.note?.[L] || d.note?.en || "";
  hud.showTooltip(x, y, title, body, true);
}

/* ------------------------------------------------------------- loop */

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  const t = clock.elapsedTime;

  controls.update(dt);

  // portal animation + proximity trigger
  for (const p of state.portals) {
    p.update(t, dt, p === hoveredPortal);
    if (
      controls.enabled && !state.transitioning &&
      performance.now() > state.portalCooldown &&
      p.contains(camera.position)
    ) {
      transition(p);
    }
  }

  // hotspot pulse + fade (AI X-Ray layer)
  xray.update(t, dt);

  renderer.render(scene, camera);
}

function onResize() {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}
