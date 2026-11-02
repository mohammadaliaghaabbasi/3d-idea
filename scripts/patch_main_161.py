#!/usr/bin/env python3
"""Patch public/js/main.js — Stage 1.6.1:
purge the furniture GLB layer (Rule A/B), wire the elastic walk envelope,
dome-fit the doorway ring, flash obstacle halos on bump, expose dome stats."""
import sys
from pathlib import Path

P = Path("/home/z/my-project/3d-idea/public/js/main.js")
src = P.read_text()

def rep(old, new, tag, count=1):
    global src
    if src.count(old) != count:
        sys.exit(f"PATCH FAIL {tag}: found {src.count(old)}x (want {count}x)")
    src = src.replace(old, new)
    print(f"  ok: {tag}")

# 1) drop the GLTFLoader import
rep('import { GLTFLoader } from "../vendor/GLTFLoader-0.160.0.js";\n', "", "drop GLTFLoader import")

# 2) state: no furnitureObj
rep("  meshObj: null,\n  furnitureObj: null,\n", "  meshObj: null,\n", "state purge furnitureObj")

# 3) no gltfLoader instance
rep("let renderer, scene, camera, controls, hud, audio;\nconst gltfLoader = new GLTFLoader();\n",
    "let renderer, scene, camera, controls, hud, audio;\n", "drop gltfLoader instance")

# 4) roomStats: dome + envelope + halos; texture = crisp pano
rep("""    roomStats: () => {
      if (!state.meshObj) return null;
      const s = { ...state.meshObj.stats };
      s.furniture = state.furnitureObj ? state.furnitureObj.stats : null;
      s.textureUrl = state.room ? (state.room.shell_texture || state.room.panorama) : null;
      s.obstacles = state.room?.walk?.obstacles?.length ?? 0;
      return s;
    },""",
    """    roomStats: () => {
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
    halos: () => (state.fx && state.fx.halos ? state.fx.halos.count : 0),""", "roomStats + hooks")

# 5) purge the furniture layer functions (loadFurnitureLayer + disposeFurnitureLayer)
i = src.find("/**\n * Stage 1.6 LAYER 2")
if i < 0:
    sys.exit("PATCH FAIL: furniture layer block start not found")
j = src.find("function routeFor(idx)")
if j < 0:
    sys.exit("PATCH FAIL: routeFor anchor not found")
src = src[:i] + src[j:]
print("  ok: purge loadFurnitureLayer/disposeFurnitureLayer")

# 6) loadRoom: single build, envelope wiring, dome-fit ring
rep("""  hud.setLoadProgress(0.15);
  const [meshObj, furnitureObj] = await Promise.all([
    buildRoomVolume(room, renderer),
    loadFurnitureLayer(room),
  ]);
  hud.setLoadProgress(0.85);

  if (state.meshObj) {
    scene.remove(state.meshObj.mesh);
    state.meshObj.dispose();
    state.meshObj = null;
  }
  if (state.furnitureObj) {
    scene.remove(state.furnitureObj.group);
    disposeFurnitureLayer(state.furnitureObj);
    state.furnitureObj = null;
  }""",
    """  hud.setLoadProgress(0.15);
  const meshObj = await buildRoomVolume(room, renderer);
  hud.setLoadProgress(0.85);

  if (state.meshObj) {
    scene.remove(state.meshObj.mesh);
    state.meshObj.dispose();
    state.meshObj = null;
  }""", "loadRoom: single build (Rule A — crisp pano dome, no GLB layer)")

rep("""  state.meshObj = meshObj;
  scene.add(meshObj.mesh);
  state.furnitureObj = furnitureObj;
  if (furnitureObj) scene.add(furnitureObj.group);
  state.roomIdx = idx;
  state.room = room;

  // physics world + floor walk FX
  state.world = new WalkWorld(room);
  state.fx = new WalkFX(scene, room);
  controls.setWorld(state.world);
  controls.setRoom(room);
  audio.setRoom(room.audio || {});

  // one verified doorway waypoint → routed next room
  const { target } = routeFor(idx);
  const wp = new Waypoint(room.portals[0], state.db.rooms[target]);
  scene.add(wp.group);
  state.waypoint = wp;""",
    """  state.meshObj = meshObj;
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
  state.waypoint = wp;""", "loadRoom: envelope + halos + dome-fit ring")

# 7) helpers: computeEnvelope + fitWaypointToDome (insert before warpThrough)
rep("""/* ------------------------------------------------------------- warp */""",
    """/* --------------------------------------------------- Stage 1.6.1 helpers */

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
    const dist = Math.hypot(dx, dz);
    const effR = o.type === "cylinder" ? (o.r || 0) : Math.hypot(o.hw || 0, o.hd || 0);
    const reach = dist - effR - 0.34;            // player reaches the collider face
    if (reach > base + 0.05) {
      channels.push({ ang: Math.atan2(dz, dx), reach, half: THREE.MathUtils.degToRad(14) });
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

/* ------------------------------------------------------------- warp */""", "envelope + ring-fit helpers")

# 8) handleBump: halo flash
rep("""function handleBump(bump) {
  if (!bump) return;
  const label = bump.label[i18n.lang] || bump.label.en;
  hud.showBump(`${i18n.t.bump_prefix} ${label}`);
  audio.bump();""",
    """function handleBump(bump) {
  if (!bump) return;
  const label = bump.label[i18n.lang] || bump.label.en;
  hud.showBump(`${i18n.t.bump_prefix} ${label}`);
  audio.bump();
  if (state.fx && state.fx.halos && bump.ob) state.fx.halos.flash(bump.ob);  // glass halo flash""", "handleBump halo flash")

# 9) header note
rep(""" * Stage 1.5 laws (locked 2026-11-02):""",
    """ * Stage 1.6.1 (owner emergency order 2026-11-02): the furniture GLB layer
 * and inpainted shells are PURGED (spike/smudge audit).  Rooms render as a
 * smooth RELIEF DOME (room.js) textured with the crisp original pano; real
 * physics colliders + glass floor halos stay (collider.js); walking is
 * bounded by the elastic radial envelope (controls.js).
 *
 * Stage 1.5 laws (locked 2026-11-02):""", "header note")

P.write_text(src)
print("main.js patched OK")
