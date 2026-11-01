/**
 * PANODROME — Glassmorphism HUD controller
 * Bottom portal-mode bar, room/attribution card, EN⇄FA RTL toggle, tooltips,
 * loading + intro overlays, help panel, touch walk pad.
 */
import { i18n } from "./i18n.js";

const $ = (id) => document.getElementById(id);

export class HUD {
  constructor() {
    this.el = {
      roomCard: $("room-card"),
      roomIndex: $("room-index"),
      roomName: $("room-name"),
      roomDesc: $("room-desc"),
      roomCreator: $("room-creator"),
      roomSource: $("room-source"),
      sysBar: $("sys-bar"),
      modeBar: $("mode-bar"),
      modeLabel: $("mode-label"),
      modeHint: $("mode-hint"),
      walkPad: $("walk-pad"),
      btnWalk: $("btn-walk"),
      btnLang: $("btn-lang"),
      btnSound: $("btn-sound"),
      btnHelp: $("btn-help"),
      helpPanel: $("help-panel"),
      tooltip: $("tooltip"),
      tooltipTitle: $("tooltip-title"),
      tooltipBody: $("tooltip-body"),
      loading: $("loading"),
      loadFill: $("load-fill"),
      loadText: $("load-text"),
      intro: $("intro"),
      introBg: $("intro-bg"),
      introTag: $("intro-tag"),
      introSub: $("intro-sub"),
      btnEnter: $("btn-enter"),
      fade: $("fade"),
    };
    this.helpOpen = false;
    this._applyStrings();
    i18n.onChange(() => this._applyStrings());
  }

  _applyStrings() {
    const t = i18n.t;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (t[key]) el.textContent = t[key];
    });
    this.el.modeLabel.textContent = t.mode_label;
    if (this._mode) this.setMode(this._mode);
    if (this._room && this._idx !== undefined) this.setRoom(this._room, this._idx, this._total);
    this.el.introTag.textContent = t.intro_tag;
    this.el.introSub.textContent = t.intro_sub;
  }

  // ------------------------------------------------------------- intro / loading
  initIntro(previewUrl, onEnter) {
    this.el.introBg.style.backgroundImage = `url(${previewUrl})`;
    this.el.btnEnter.addEventListener("click", onEnter);
  }

  hideIntro() {
    const el = this.el.intro;
    el.style.transition = "opacity 0.9s ease";
    el.style.opacity = 0;
    setTimeout(() => el.classList.add("hud-hidden"), 950);
  }

  showLoading(show) {
    this.el.loading.classList.toggle("hud-hidden", !show);
  }

  setLoadProgress(p) {
    this.el.loadFill.style.width = Math.round(p * 100) + "%";
    this.el.loadText.textContent = i18n.t.loading;
  }

  // ------------------------------------------------------------- room info
  setRoom(room, idx, total) {
    this._room = room; this._idx = idx; this._total = total;
    const t = i18n.t, L = i18n.lang;
    this.el.roomIndex.textContent = t.room_of(idx + 1, total);
    this.el.roomName.textContent = room.name[L] || room.name.en;
    this.el.roomDesc.textContent = room.description[L] || room.description.en;
    this.el.roomCreator.textContent = `${t.by} ${room.attribution.creator} ·`;
    this.el.roomSource.textContent = `${room.attribution.source} · ${room.attribution.license}`;
    this.el.roomSource.href = room.attribution.url;
  }

  // ------------------------------------------------------------- modes
  setMode(mode) {
    this._mode = mode;
    document.querySelectorAll(".mode-btn").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-mode") === mode);
    });
    this.el.modeHint.textContent = i18n.t.mode_hint[mode] || "";
  }

  onModeChange(cb) {
    document.querySelectorAll(".mode-btn").forEach((b) => {
      b.addEventListener("click", () => cb(b.getAttribute("data-mode")));
    });
  }

  onLangToggle(cb) { this.el.btnLang.addEventListener("click", cb); }
  onSoundToggle(cb) { this.el.btnSound.addEventListener("click", cb); }
  onHelpToggle(cb) { this.el.btnHelp.addEventListener("click", cb); }

  setSoundIcon(muted) {
    this.el.btnSound.classList.toggle("muted", muted);
  }

  toggleHelp() {
    this.helpOpen = !this.helpOpen;
    this.el.helpPanel.classList.toggle("hud-hidden", !this.helpOpen);
  }

  // ------------------------------------------------------------- walk pad (touch)
  bindWalkPad(controls) {
    const isTouch = matchMedia("(pointer: coarse)").matches;
    if (!isTouch) return;
    this.el.walkPad.classList.remove("hud-hidden");
    const btn = this.el.btnWalk;
    const on = (e) => { e.preventDefault(); controls.autoWalk = true; };
    const off = () => { controls.autoWalk = false; };
    btn.addEventListener("pointerdown", on);
    btn.addEventListener("pointerup", off);
    btn.addEventListener("pointercancel", off);
    btn.addEventListener("pointerleave", off);
  }

  // ------------------------------------------------------------- tooltips
  showTooltip(x, y, title, body, chip) {
    const el = this.el.tooltip;
    this.el.tooltipTitle.innerHTML =
      (chip ? `<span class="chip-ai">${i18n.t.inspector_chip}</span>` : "") + title;
    this.el.tooltipBody.innerHTML = body;
    el.classList.remove("hud-hidden");
    const pad = 12;
    const w = el.offsetWidth, h = el.offsetHeight;
    let px = x, py = y;
    if (x - w / 2 < pad) px = w / 2 + pad;
    if (x + w / 2 > innerWidth - pad) px = innerWidth - w / 2 - pad;
    if (y - h - 20 < pad) py = h + pad + 4;
    el.style.left = px + "px";
    el.style.top = py + "px";
  }

  hideTooltip() {
    this.el.tooltip.classList.add("hud-hidden");
  }

  // ------------------------------------------------------------- hud visibility
  showHud() {
    [this.el.roomCard, this.el.sysBar, this.el.modeBar].forEach((el) =>
      el.classList.remove("hud-hidden")
    );
  }
}
