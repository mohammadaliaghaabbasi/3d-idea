/**
 * PANODROME — Stage 1 · Luxury "Invisible UI" HUD
 *
 * 92% of the viewport stays pure, unobstructed architecture. Everything else:
 *   · top-inline-start  — one compact glass pill: Room Title · Designer · Source
 *   · top-inline-end    — two 38px circular glass buttons: [EN/فا] [⛶ reset/fullscreen]
 *   · bottom-centre     — one floating glass capsule: ‹ prev | name (i of 6) | next › + hint
 *   · touch only        — a minimal forward/back thumb pad on the inline-end edge
 * Zero-overflow guarantee: max-widths + ellipsis everywhere (see style.css).
 */
import { i18n } from "./i18n.js";

export class HUD {
  constructor() {
    this.el = {};
    const camel = (s) => s.replace(/-(.)/g, (_, c) => c.toUpperCase());
    for (const id of [
      "room-pill", "room-title", "room-designer", "room-source",
      "view-actions", "btn-lang", "btn-view", "btn-view-reset", "btn-view-full",
      "nav-capsule", "nav-prev", "nav-next", "nav-name", "nav-count", "nav-hint",
      "walk-pad", "btn-fwd", "btn-back",
      "wp-chip", "wp-chip-label",
      "loading", "load-fill", "load-text",
      "intro", "intro-bg", "intro-tag", "intro-sub", "btn-enter", "intro-hint", "intro-credit",
      "fade", "webgl-error",
    ]) {
      this.el[camel(id)] = document.getElementById(id);
    }
    this._onChip = null;
    this._chipRoom = null;
    this.el.wpChip?.addEventListener("click", () => this._onChip && this._onChip(this._chipRoom));
    this._applyIntroStrings();
    i18n.onChange(() => this._applyIntroStrings());
  }

  _applyIntroStrings() {
    const t = i18n.t;
    this.el.introTag.textContent = t.tagline;
    this.el.introSub.textContent = t.intro_sub;
    this.el.introHint.textContent = t.intro_hint;
    this.el.btnEnter.querySelector("span").textContent = t.enter;
    this.el.introCredit.textContent = t.credit;
    this.el.btnLang.textContent = t.lang_btn;
    this.el.navHint.textContent = t.hint;
    this.el.navPrev.setAttribute("aria-label", t.nav_prev);
    this.el.navNext.setAttribute("aria-label", t.nav_next);
    this.el.btnFwd.setAttribute("aria-label", t.walk_f);
    this.el.btnBack.setAttribute("aria-label", t.walk_b);
    this.el.loadText.textContent = t.loading;
    this._setViewTitles();
    if (this._room) this.setRoom(this._room, this._idx, this._total);
  }

  /* ------------------------------------------------------------ intro / load */

  initIntro(previewUrl, onEnter) {
    this.el.introBg.style.backgroundImage = `url(${previewUrl})`;
    this.el.btnEnter.addEventListener("click", onEnter, { once: true });
  }

  hideIntro() { this.el.intro.classList.add("gone"); }
  showHud() {
    for (const key of ["roomPill", "viewActions", "navCapsule"]) {
      this.el[key].classList.remove("hud-hidden");
    }
    if (matchMedia("(pointer: coarse)").matches) {
      document.body.classList.add("touch");
      this.el.walkPad.classList.remove("hud-hidden");
    }
  }

  showLoading(show) { this.el.loading.classList.toggle("hud-hidden", !show); }
  setLoadProgress(p) { this.el.loadFill.style.width = `${Math.round(p * 100)}%`; }

  /* ------------------------------------------------------------ room */

  setRoom(room, idx, total) {
    this._room = room; this._idx = idx; this._total = total;
    const t = i18n.t, L = i18n.lang;
    const name = room.name[L] || room.name.en;
    this.el.roomTitle.textContent = name;
    this.el.roomTitle.title = name;
    this.el.roomDesigner.textContent = room.attribution.creator;
    this.el.roomSource.textContent = `${room.attribution.source} · ${room.attribution.license}`;
    this.el.roomSource.href = room.attribution.url;
    this.el.navName.textContent = name;
    this.el.navName.title = name;
    this.el.navCount.textContent = t.counter(idx + 1, total);
  }

  /* ------------------------------------------------------------ view button */

  _setViewTitles() {
    const glided = this._glided;
    this.el.btnView.setAttribute("title", glided ? i18n.t.reset_view : i18n.t.fullscreen);
    this.el.btnView.setAttribute("aria-label", glided ? i18n.t.reset_view : i18n.t.fullscreen);
    this.el.btnViewReset.style.display = glided ? "" : "none";
    this.el.btnViewFull.style.display = glided ? "none" : "";
  }

  setGlided(glided) {
    if (glided === this._glided) return;
    this._glided = glided;
    this._setViewTitles();
  }

  /* ------------------------------------------------------------ bindings */

  onLangToggle(fn) { this.el.btnLang.addEventListener("click", fn); }
  onViewButton(fn) { this.el.btnView.addEventListener("click", fn); }
  onNavigate(fn) {
    this.el.navPrev.addEventListener("click", () => fn(-1));
    this.el.navNext.addEventListener("click", () => fn(1));
  }

  /** Thumb pad: hold to walk. */
  bindWalkPad(controls) {
    const hold = (btn, dir) => {
      const set = (v) => (e) => {
        e.preventDefault();
        controls.pad = v ? dir : 0;
      };
      btn.addEventListener("pointerdown", set(true));
      btn.addEventListener("pointerup", set(false));
      btn.addEventListener("pointerleave", set(false));
      btn.addEventListener("pointercancel", set(false));
    };
    hold(this.el.btnFwd, 1);
    hold(this.el.btnBack, -1);
  }

  /* ------------------------------------------------------------ waypoint chip */

  onWaypointChip(fn) { this._onChip = fn; }

  showWaypointChip(room, x, y) {
    this._chipRoom = room;
    const L = i18n.lang;
    this.el.wpChipLabel.textContent = `${i18n.t.enter_room} ${room.name[L] || room.name.en}`;
    this.el.wpChip.classList.remove("hud-hidden");
    this.placeWaypointChip(x, y);
  }

  placeWaypointChip(x, y) {
    const r = this.el.wpChip.getBoundingClientRect();
    const PAD = 10;
    const cx = Math.min(Math.max(x, PAD + r.width / 2), innerWidth - PAD - r.width / 2);
    const cy = Math.min(Math.max(y - r.height - 18, PAD + r.height / 2), innerHeight - PAD - r.height / 2);
    this.el.wpChip.style.left = `${Math.round(cx)}px`;
    this.el.wpChip.style.top = `${Math.round(cy)}px`;
  }

  hideWaypointChip() {
    this._chipRoom = null;
    this.el.wpChip.classList.add("hud-hidden");
  }

  get chipOpen() { return !!this._chipRoom; }
}
