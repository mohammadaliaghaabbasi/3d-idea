/**
 * PANODROME — Phase 2 · AI X-Ray Material & Furniture Hotspots
 *
 * Reads hotspots from rooms_db.json (detected by skills/vision_hotspots.py —
 * a VLM pass with spherical yaw/pitch coordinates projected onto the depth
 * mesh) and renders them as subtle pulsing glass pins.
 *
 *  * HUD toggle `#btn-xray`  — pins on/off (chip turns active)
 *  * hold SPACE              — peek while held
 *  * hover (480 ms dwell)    — opens the glassmorphism detail card
 *  * click                   — opens it instantly
 *
 * Card is fully bilingual (EN/FA RTL) and reacts to live language switches.
 */
import * as THREE from "three";
import { i18n } from "./i18n.js";

/** Material category → accent colour (used for the pin core + card dot). */
const CAT_COLORS = {
  wood: "#e0b075",
  stone: "#c6cbd6",
  metal: "#9fd4e8",
  glass: "#7fe3f2",
  textile: "#f0a7c8",
  ceramic: "#8adfd0",
  lighting: "#ffe08a",
  concrete: "#aab2bd",
  brick: "#e2917a",
  plaster: "#e8dcc8",
  vegetation: "#a4e6a0",
  other: "#a78bfa",
};

export class XRayLayer {
  /** @param {THREE.Scene} scene */
  constructor(scene) {
    this.scene = scene;
    this.pins = [];          // {def, sprite, baseScale, phase, matColor}
    this.active = false;     // toggle state
    this.holdActive = false; // SPACE peek
    this.hovered = null;
    this.openDef = null;
    this._dwellTimer = null;
    this._texCache = new Map();

    this.el = {
      btn: document.getElementById("btn-xray"),
      card: document.getElementById("xray-card"),
      chip: document.getElementById("xray-chip"),
      title: document.getElementById("xray-title"),
      catDot: document.getElementById("xray-cat-dot"),
      catLabel: document.getElementById("xray-cat-label"),
      desc: document.getElementById("xray-desc"),
      close: document.getElementById("xray-close"),
      hint: document.getElementById("xray-hint"),
    };
    this._bind();
    i18n.onChange(() => {
      this._applyStrings();
      if (this.openDef) this._fillCard(this.openDef);
    });
    this._applyStrings();
  }

  /* ------------------------------------------------------------ dom / input */

  _bind() {
    this.el.btn.addEventListener("click", () => this.toggle());
    this.el.close.addEventListener("click", () => this.closeCard());
    this._onKeyDown = (e) => {
      if (e.code !== "Space" || e.repeat) return;
      this.holdActive = true;
      this._syncVisibility();
    };
    this._onKeyUp = (e) => {
      if (e.code !== "Space") return;
      this.holdActive = false;
      this._syncVisibility();
    };
    this._onBlur = () => {
      this.holdActive = false;
      this._syncVisibility();
    };
    window.addEventListener("keydown", this._onKeyDown);
    window.addEventListener("keyup", this._onKeyUp);
    window.addEventListener("blur", this._onBlur);
    // click outside card (on the 3D canvas) closes it — handled via document
    this._onDocDown = (e) => {
      if (!this.openDef) return;
      if (this.el.card.contains(e.target) || this.el.btn.contains(e.target)) return;
      this.closeCard();
    };
    document.addEventListener("pointerdown", this._onDocDown, true);
  }

  _applyStrings() {
    const t = i18n.t;
    this.el.btn.title = `${t.xray} (${t.xray_hold})`;
    this.el.chip.textContent = t.xray_chip;
    this.el.hint.textContent = t.xray_hint;
  }

  toggle(force) {
    this.active = force !== undefined ? force : !this.active;
    this.el.btn.classList.toggle("active", this.active);
    this._syncVisibility();
  }

  get visible() {
    return this.active || this.holdActive;
  }

  _syncVisibility() {
    const on = this.visible;
    this.pins.forEach((p) => { p.targetOpacity = on ? 1 : 0; });
    if (!on) {
      this._clearDwell();
      if (this.hovered) { this.hovered = null; this._applyStrings(); }
    }
  }

  /* ------------------------------------------------------------ room swap */

  /** Rebuild pins for a room (disposes the previous room's sprites). */
  loadRoom(room) {
    this.disposePins();
    this.closeCard(true);
    (room.hotspots || []).forEach((def, i) => {
      const color = CAT_COLORS[def.material_category] || CAT_COLORS.other;
      const sprite = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: this._pinTexture(color),
          transparent: true,
          depthTest: true,
          opacity: 0,
          depthWrite: false,
        })
      );
      sprite.position.fromArray(def.position);
      sprite.scale.setScalar(0.13);
      sprite.renderOrder = 6;
      sprite.visible = false;
      this.scene.add(sprite);
      this.pins.push({
        def, sprite,
        baseScale: 0.13,
        phase: i * 1.7 + def.position[0] * 5.3,
        matColor: color,
        targetOpacity: this.visible ? 1 : 0,
      });
    });
  }

  disposePins() {
    this.pins.forEach((p) => {
      this.scene.remove(p.sprite);
      p.sprite.material.dispose();
    });
    this.pins = [];
  }

  /** Sprites currently eligible for raycasting (hidden pins are skipped). */
  pinMeshes() {
    return this.visible ? this.pins.map((p) => p.sprite) : [];
  }

  /* ------------------------------------------------------------ interaction */

  /** Called by main.js on pointermove; `hotspot` is one entry of this.pins. */
  setHover(hotspot) {
    if (hotspot === this.hovered) return;
    this.hovered = hotspot;
    this._clearDwell();
    if (hotspot && this.visible && !this.openDef) {
      this._dwellTimer = setTimeout(() => {
        if (this.hovered === hotspot) this.openCard(hotspot.def);
      }, 480);
    }
  }

  _clearDwell() {
    if (this._dwellTimer) { clearTimeout(this._dwellTimer); this._dwellTimer = null; }
  }

  openCard(def) {
    this.openDef = def;
    this._fillCard(def);
    this.el.card.classList.add("open");
  }

  closeCard(instant) {
    if (!this.openDef && !this.el.card.classList.contains("open")) return;
    this.openDef = null;
    if (instant) this.el.card.classList.remove("open", "opening");
    else this.el.card.classList.remove("open");
  }

  _fillCard(def) {
    const L = i18n.lang;
    const t = i18n.t;
    this.el.title.textContent = def.title?.[L] || def.title?.en || def.label?.[L] || def.label?.en || "";
    this.el.desc.textContent = def.desc?.[L] || def.desc?.en || def.note?.[L] || def.note?.en || "";
    const cat = def.material_category || "other";
    this.el.catDot.style.background = CAT_COLORS[cat] || CAT_COLORS.other;
    this.el.catLabel.textContent = t["cat_" + cat] || t.cat_other;
    this.el.catLabel.style.color = CAT_COLORS[cat] || CAT_COLORS.other;
  }

  /* ------------------------------------------------------------ frame loop */

  update(t, dt) {
    const target = this.visible ? 1 : 0;
    for (const p of this.pins) {
      const m = p.sprite.material;
      m.opacity += ((p.targetOpacity ?? target) - m.opacity) * Math.min(1, dt * 7);
      const shown = m.opacity > 0.02;
      p.sprite.visible = shown;
      if (shown) {
        const pulse = 1 + 0.14 * Math.sin(t * 2.8 + p.phase);
        const hover = p === this.hovered ? 1.32 : 1;
        p.sprite.scale.setScalar(p.baseScale * pulse * hover);
      }
    }
  }

  _pinTexture(color) {
    if (this._texCache.has(color)) return this._texCache.get(color);
    const s = 96;
    const cv = document.createElement("canvas");
    cv.width = s; cv.height = s;
    const ctx = cv.getContext("2d");
    const c = s / 2;
    // soft glow halo
    const g = ctx.createRadialGradient(c, c, s * 0.10, c, c, s * 0.5);
    g.addColorStop(0, hexA(color, 0.34));
    g.addColorStop(0.65, hexA(color, 0.10));
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, s, s);
    // glass ring
    ctx.strokeStyle = "rgba(238,242,248,0.95)";
    ctx.lineWidth = 4;
    ctx.beginPath(); ctx.arc(c, c, s * 0.30, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = hexA(color, 0.55);
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(c, c, s * 0.38, 0, Math.PI * 2); ctx.stroke();
    // material core dot (slightly larger for readability at room scale)
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(c, c, s * 0.135, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,0.92)";
    ctx.beginPath(); ctx.arc(c, c, s * 0.055, 0, Math.PI * 2); ctx.fill();
    const tex = new THREE.CanvasTexture(cv);
    tex.colorSpace = THREE.SRGBColorSpace;
    this._texCache.set(color, tex);
    return tex;
  }
}

function hexA(hex, a) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}
