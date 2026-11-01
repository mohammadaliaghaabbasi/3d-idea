/**
 * PANODROME — Creator Upload Studio (Phase 3)
 *
 * "Upload Your 360° Space" — a user drops any equirectangular panorama
 * (JPG/PNG/WebP, or pastes an image URL), fills in a couple of fields and
 * Panodrome turns it into a walkable room RIGHT IN THE BROWSER:
 *
 *   · client-side depth map on a canvas — analytic box-room ray prior
 *     (identical maths to skills/ingest_polyhaven.py:procedural_depth),
 *     so the displaced-sphere engine gets a real 3D volume instantly;
 *   · click the panorama strip to place 1–2 door portals (green) and up to
 *     3 material pins (amber);
 *   · the room joins the live session immediately (routing, portals, audio,
 *     X-Ray pins) and persists in IndexedDB across visits;
 *   · one-click export of the full room as a JSON contribution package
 *     (panorama + depth embedded as data URLs).
 */
import { i18n } from "./i18n.js";

const DB_NAME = "panodrome_uploads";
const STORE = "rooms";
const DEPTH_W = 1024, DEPTH_H = 512;

/* ---------------------------------------------------------------- IndexedDB */

function idb() {
  return new Promise((res, rej) => {
    const rq = indexedDB.open(DB_NAME, 1);
    rq.onupgradeneeded = () => rq.result.createObjectStore(STORE, { keyPath: "id" });
    rq.onsuccess = () => res(rq.result);
    rq.onerror = () => rej(rq.error);
  });
}

async function idbPut(room) {
  const db = await idb();
  return new Promise((res, rej) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(room);
    tx.oncomplete = res;
    tx.onerror = () => rej(tx.error);
  });
}

async function idbAll() {
  try {
    const db = await idb();
    return await new Promise((res, rej) => {
      const rq = db.transaction(STORE, "readonly").objectStore(STORE).getAll();
      rq.onsuccess = () => res(rq.result || []);
      rq.onerror = () => rej(rq.error);
    });
  } catch {
    return [];
  }
}

async function idbDelete(id) {
  const db = await idb();
  return new Promise((res) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(id);
    tx.oncomplete = res;
    tx.onerror = res;
  });
}

/* ---------------------------------------------------------------- maths */

function boxExit(cx, cy, cz, dx, dy, dz, W, H, D) {
  let t = Infinity;
  const faces = [
    [dx, W / 2 - cx, -W / 2 - cx],
    [dy, H - cy, 0 - cy],
    [dz, D / 2 - cz, -D / 2 - cz],
  ];
  for (const [d, hi, lo] of faces) {
    if (d > 1e-9) t = Math.min(t, hi / d);
    else if (d < -1e-9) t = Math.min(t, lo / d);
  }
  return t;
}

function equirectDir(frac, pitchDeg) {
  const phi = 2 * Math.PI * frac;
  const theta = Math.PI / 2 - (pitchDeg * Math.PI) / 180;
  const st = Math.sin(theta);
  return [-Math.cos(phi) * st, Math.cos(theta), Math.sin(phi) * st];
}

/** Two-channel uint16 depth PNG (R=hi, G=lo) as a data URL — box prior. */
function makeDepthDataURL(shape, cam) {
  const cv = document.createElement("canvas");
  cv.width = DEPTH_W; cv.height = DEPTH_H;
  const ctx = cv.getContext("2d");
  const img = ctx.createImageData(DEPTH_W, DEPTH_H);
  const [W, H, D] = shape;
  const corner = Math.max(
    Math.hypot(W / 2 - cam[0], H - cam[1], D / 2 - cam[2]),
    Math.hypot(-W / 2 - cam[0], 0 - cam[1], -D / 2 - cam[2]),
    Math.hypot(W / 2 - cam[0], 0 - cam[1], -D / 2 - cam[2]),
    Math.hypot(-W / 2 - cam[0], H - cam[1], D / 2 - cam[2]),
  );
  const dmax = corner * 1.1;
  for (let y = 0; y < DEPTH_H; y++) {
    const theta = (Math.PI * (y + 0.5)) / DEPTH_H;
    for (let x = 0; x < DEPTH_W; x++) {
      const phi = 2 * Math.PI * (x + 0.5) / DEPTH_W;
      const st = Math.sin(theta);
      const t = boxExit(cam[0], cam[1], cam[2],
        -Math.cos(phi) * st, Math.cos(theta), Math.sin(phi) * st, W, H, D);
      const v = Math.min(1, t / dmax);
      const v16 = Math.round(v * 65535);
      const p = (y * DEPTH_W + x) * 4;
      img.data[p] = (v16 >> 8) & 0xff;
      img.data[p + 1] = v16 & 0xff;
      img.data[p + 2] = 0;
      img.data[p + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return { url: cv.toDataURL("image/png"), dmax: Math.round(dmax * 1000) / 1000 };
}

function loadImage(src) {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = () => rej(new Error("image load failed"));
    img.src = src;
  });
}

/* ---------------------------------------------------------------- studio */

export class UploadStudio {
  /**
   * @param {{ onRoomCreated: (room) => void }} deps
   */
  constructor(deps) {
    this.deps = deps;
    this.img = null;
    this.panoURL = null;
    this.markers = { doors: [], pins: [] };
    this.tool = "door"; // door | pin
    this.persisted = [];

    this.el = {
      btn: document.getElementById("btn-upload"),
      modal: document.getElementById("upload-studio"),
      backdrop: document.getElementById("upload-backdrop"),
      close: document.getElementById("us-close"),
      drop: document.getElementById("us-drop"),
      file: document.getElementById("us-file"),
      url: document.getElementById("us-url"),
      urlGo: document.getElementById("us-url-go"),
      canvas: document.getElementById("us-canvas"),
      tools: document.getElementById("us-tools"),
      toolDoor: document.getElementById("us-tool-door"),
      toolPin: document.getElementById("us-tool-pin"),
      pinLabel: document.getElementById("us-pin-label"),
      title: document.getElementById("us-title"),
      creator: document.getElementById("us-creator"),
      portfolio: document.getElementById("us-portfolio"),
      style: document.getElementById("us-style"),
      type: document.getElementById("us-type"),
      size: document.getElementById("us-size"),
      go: document.getElementById("us-go"),
      exportBtn: document.getElementById("us-export"),
      status: document.getElementById("us-status"),
      hint: document.getElementById("us-drop-hint"),
    };
    this._bind();
    i18n.onChange(() => this._applyStrings());
    this._applyStrings();
  }

  _bind() {
    this.el.btn.addEventListener("click", () => this.open());
    this.el.close.addEventListener("click", () => this.close());
    this.el.backdrop.addEventListener("click", () => this.close());
    this.el.drop.addEventListener("click", () => this.el.file.click());
    this.el.drop.addEventListener("dragover", (e) => { e.preventDefault(); this.el.drop.classList.add("drag"); });
    this.el.drop.addEventListener("dragleave", () => this.el.drop.classList.remove("drag"));
    this.el.drop.addEventListener("drop", (e) => {
      e.preventDefault();
      this.el.drop.classList.remove("drag");
      const f = e.dataTransfer?.files?.[0];
      if (f) this._readFile(f);
    });
    this.el.file.addEventListener("change", () => {
      if (this.el.file.files[0]) this._readFile(this.el.file.files[0]);
    });
    this.el.urlGo.addEventListener("click", () => this._loadURL());
    this.el.url.addEventListener("keydown", (e) => { if (e.key === "Enter") this._loadURL(); });
    this.el.toolDoor.addEventListener("click", () => this.setTool("door"));
    this.el.toolPin.addEventListener("click", () => this.setTool("pin"));
    this.el.canvas.addEventListener("click", (e) => this._place(e));
    this.el.go.addEventListener("click", () => this._create());
    this.el.exportBtn.addEventListener("click", () => this.exportPackage());
  }

  _applyStrings() {
    const t = i18n.t;
    if (!t.us_title) return;
    const set = (id, v) => { const el = document.getElementById(id); if (el && v) el.textContent = v; };
    set("us-head", t.us_head);
    set("us-sub", t.us_subhead);
    set("us-drop-title", t.us_drop_title);
    set("us-drop-hint", t.us_drop_hint);
    set("us-browse", t.us_browse);
    set("us-place-head", t.us_place_head);
    set("us-fields-head", t.us_fields_head);
    this.el.title.placeholder = t.us_title;
    this.el.creator.placeholder = t.us_creator;
    this.el.portfolio.placeholder = t.us_portfolio;
    this.el.pinLabel.placeholder = t.us_pin_label;
    this.el.url.placeholder = t.us_url;
    this.el.go.textContent = t.us_go;
    this.el.exportBtn.textContent = t.us_export;
    this.el.toolDoor.textContent = t.us_tool_door;
    this.el.toolPin.textContent = t.us_tool_pin;
    this.el.pinLabel.classList.toggle("hud-hidden", this.tool !== "pin");
    // style + room type options (bilingual labels)
    const L = i18n.lang;
    const fill = (sel, list) => {
      const el = document.getElementById(sel);
      if (el && list) {
        el.innerHTML = list.map((o) => `<option value="${o.v}">${o[L] || o.en}</option>`).join("");
      }
    };
    fill("us-style", t.us_style_options);
    fill("us-type", t.us_type_options);
    this._status(this.img ? t.us_ready : t.us_drop_hint);
  }

  async loadPersisted() {
    this.persisted = await idbAll();
    return this.persisted;
  }

  open() {
    this.el.modal.classList.add("open");
    this.el.backdrop.classList.add("open");
  }

  close() {
    this.el.modal.classList.remove("open");
    this.el.backdrop.classList.remove("open");
  }

  setTool(tool) {
    this.tool = tool;
    this.el.toolDoor.classList.toggle("active", tool === "door");
    this.el.toolPin.classList.toggle("active", tool === "pin");
    this.el.pinLabel.classList.toggle("hud-hidden", tool !== "pin");
  }

  _status(msg, error) {
    this.el.status.textContent = msg;
    this.el.status.classList.toggle("error", !!error);
  }

  _readFile(f) {
    if (!/^image\/(jpeg|png|webp)/.test(f.type)) {
      this._status(i18n.t.us_bad_type, true);
      return;
    }
    const rd = new FileReader();
    rd.onload = () => this._setImage(rd.result, f.name);
    rd.onerror = () => this._status("read error", true);
    rd.readAsDataURL(f);
  }

  async _loadURL() {
    const url = this.el.url.value.trim();
    if (!url) return;
    this._status(i18n.t.us_loading);
    try {
      const r = await fetch(url, { mode: "cors" });
      if (!r.ok) throw new Error(r.status);
      const blob = await r.blob();
      const rd = new FileReader();
      rd.onload = () => this._setImage(rd.result, url);
      rd.readAsDataURL(blob);
    } catch (e) {
      this._status(i18n.t.us_url_fail, true);
    }
  }

  async _setImage(dataURL, name) {
    let img;
    try {
      img = await loadImage(dataURL);
    } catch { this._status("decode error", true); return; }
    const ratio = img.width / img.height;
    if (Math.abs(ratio - 2) > 0.16) {
      this._status(i18n.t.us_bad_ratio, true);
      return;
    }
    this.img = img;
    this.panoURL = dataURL;
    this.markers = { doors: [], pins: [] };
    this._draw();
    if (!this.el.title.value) this.el.title.value = name.replace(/\.[a-z]+$/i, "").slice(0, 40);
    this._status(i18n.t.us_ready);
    this.el.go.disabled = false;
  }

  _draw() {
    const cv = this.el.canvas, ctx = cv.getContext("2d");
    const w = cv.clientWidth || 640;
    const h = Math.round(w / 2);
    cv.width = w; cv.height = h;
    cv.style.height = h + "px";
    if (this.img) ctx.drawImage(this.img, 0, 0, w, h);
    const mark = (frac, pitchDeg, color, label, r) => {
      const x = frac * w;
      const y = (0.5 - pitchDeg / 180) * h;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.stroke();
      ctx.beginPath();
      ctx.arc(x, y, r + 5, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(0,0,0,0.45)"; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = color;
      ctx.font = `bold 11px ${getComputedStyle(document.body).fontFamily}`;
      ctx.fillText(label, x + r + 8, y + 4);
    };
    this.markers.doors.forEach((m, i) => mark(m.fraction, m.pitch, "#5ef08a", `D${i + 1}`, 13));
    this.markers.pins.forEach((m, i) => mark(m.fraction, m.pitch, "#ffd166", `P${i + 1}`, 11));
  }

  _place(e) {
    if (!this.img) return;
    const rect = this.el.canvas.getBoundingClientRect();
    const frac = ((e.clientX - rect.left) / rect.width) % 1;
    const pitch = Math.round(((0.5 - (e.clientY - rect.top) / rect.height) * 180));
    if (this.tool === "door") {
      if (this.markers.doors.length >= 2) { this._status(i18n.t.us_max_doors, true); return; }
      this.markers.doors.push({ fraction: frac, pitch: 0 });
    } else {
      if (this.markers.pins.length >= 3) { this._status(i18n.t.us_max_pins, true); return; }
      this.markers.pins.push({ fraction: frac, pitch, label: this.el.pinLabel.value.trim() });
    }
    this._draw();
  }

  _shape() {
    const s = this.el.size.value || "standard";
    if (s === "cozy") return [6, 3, 6];
    if (s === "grand") return [14, 8, 16];
    return [9, 4, 11];
  }

  async _create() {
    if (!this.img) { this._status(i18n.t.us_need_image, true); return; }
    const title = this.el.title.value.trim() || "My 360° Space";
    const creator = this.el.creator.value.trim();
    const portfolio = this.el.portfolio.value.trim();
    const styleTag = this.el.style.value || "contemporary";
    const roomType = this.el.type.value || "living_room";
    const [W, H, D] = this._shape();
    const cam = [0, 1.6, 0];

    this._status(i18n.t.us_building);
    await new Promise((r) => setTimeout(r, 30)); // let the status paint

    // panorama: resize to ≤4096 and re-encode
    const maxW = 4096;
    const scale = Math.min(1, maxW / this.img.width);
    const pc = document.createElement("canvas");
    pc.width = Math.round(this.img.width * scale);
    pc.height = Math.round(this.img.height * scale);
    pc.getContext("2d").drawImage(this.img, 0, 0, pc.width, pc.height);
    const panoURL = pc.toDataURL("image/jpeg", 0.85);

    // preview 512×256
    const pr = document.createElement("canvas");
    pr.width = 512; pr.height = 256;
    pr.getContext("2d").drawImage(this.img, 0, 0, 512, 256);
    const previewURL = pr.toDataURL("image/jpeg", 0.8);

    // depth + geometry
    const depth = makeDepthDataURL([W, H, D], cam);

    // portals from door markers (box-raycast anchors, like the ingest skill)
    const portals = this.markers.doors.map((m, i) => {
      const [dx, dy, dz] = equirectDir(m.fraction, 4);
      const t = boxExit(cam[0], cam[1], cam[2], dx, dy, dz, W, H, D);
      const pos = [cam[0] + dx * (t - 0.06), Math.min(Math.max(cam[1] + dy * (t - 0.06), 1.0), 2.1), cam[2] + dz * (t - 0.06)];
      const n = [-dx, 0, -dz];
      const ln = Math.hypot(n[0], n[2]) || 1;
      return {
        id: `user_p${i + 1}`,
        fraction: Math.round(m.fraction * 10000) / 10000,
        origin: "user_placed",
        position: pos.map((v) => Math.round(v * 1000) / 1000),
        normal: [n[0] / ln, 0, n[2] / ln].map((v) => Math.round(v * 1000) / 1000),
        width: 1.2, height: 2.2,
        label: { en: "Smart Portal", fa: "درگاه هوشمند" },
      };
    });

    // material pins
    const hotspots = this.markers.pins.map((m, i) => {
      const [dx, dy, dz] = equirectDir(m.fraction, m.pitch);
      const t = boxExit(cam[0], cam[1], cam[2], dx, dy, dz, W, H, D);
      const r = Math.max(0.55, t - 0.18);
      const label = m.label || (i18n.lang === "fa" ? "متریال انتخابی" : "Custom Material");
      return {
        id: `user_pin_${i + 1}`,
        origin: "user_placed",
        fraction: Math.round(m.fraction * 10000) / 10000,
        pitch: m.pitch,
        position: [cam[0] + dx * r, cam[1] + dy * r, cam[2] + dz * r].map((v) => Math.round(v * 1000) / 1000),
        title: { en: label, fa: label },
        desc: {
          en: `A material detail marked by ${creator || "the creator"} in their uploaded space.`,
          fa: `جزئیات متریالی که ${creator || "سازنده"} در فضای بارگذاری‌شده مشخص کرده است.`,
        },
        material_category: "other",
      };
    });

    const room = {
      id: "user_" + Date.now().toString(36),
      room_type: roomType,
      style_tags: [styleTag, "user-made"],
      name: { en: title, fa: title },
      description: {
        en: `A 360° space uploaded${creator ? ` by ${creator}` : ""} through the Creator Upload Studio.`,
        fa: `فضای ۳۶۰ درجه‌ای ${creator ? `ساخته‌ی ${creator}` : ""} از طریق استودیوی بارگذاری پانودروم.`,
      },
      panorama: panoURL,
      panorama_size: [pc.width, pc.height],
      preview: previewURL,
      depth_map: depth.url,
      depth_encoding: "uint16-two-channel-rgb",
      depth_backend: "browser-box-prior",
      depth_max: depth.dmax,
      room_shape: { width: W, height: H, depth: D },
      camera: { x: cam[0], y: cam[1], z: cam[2] },
      initial_view: { facing: portals[0] ? portals[0].fraction : 0.5 },
      portals,
      floor_material: "concrete",
      audio: { ambient: "room_tone", reverb: 0.32, footsteps: "concrete" },
      hotspots,
      attribution: {
        creator: creator || "Anonymous Creator",
        source: "Creator Upload",
        license: "User content",
        url: portfolio || "#",
      },
      source_platform: "Creator Upload",
      user_generated: true,
    };

    try { await idbPut(room); } catch (e) { console.warn("persist failed", e); }
    this.persisted.push(room);
    this._status(i18n.t.us_done);
    this.deps.onRoomCreated(room);
    setTimeout(() => this.close(), 700);
  }

  exportPackage() {
    idbAll().then((rooms) => {
      const pkg = {
        schema: "panodrome.contribution/1",
        project: "Panodrome",
        exported_at: new Date().toISOString(),
        rooms,
      };
      const blob = new Blob([JSON.stringify(pkg, null, 1)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "panodrome_contribution.json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    });
  }
}
