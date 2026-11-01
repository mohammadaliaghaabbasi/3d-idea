/**
 * PANODROME — Phase 2 · "My Dream House" Spatial Moodboard
 *
 *  * `+ Save Room to My House` chip (#btn-save) — collect rooms while walking
 *  * slide-over drawer (#house-drawer) — the saved spatial chain, per-room
 *    remove, shareable link, "Walk my Dream House" tour start
 *  * shareable URL  …/?house=room1,room2,room3 — anyone opening it walks
 *    exclusively through that curated sequence (both portals route along it)
 *
 * The collection persists in localStorage; the tour chain from a shared URL
 * is intentionally session-only (it is the curator's chain, not yours).
 */
import { i18n } from "./i18n.js";
import { computeHouseRoutes } from "./portals.js";

const LS_KEY = "panodrome_house_v1";

export class Moodboard {
  /**
   * @param {{ getRooms: () => Array, onRoutesChanged: () => void,
   *           onGotoRoom: (roomIndex: number) => void }} deps
   */
  constructor(deps) {
    this.deps = deps;
    this.ids = this._loadLocal();
    this.tourChain = [];     // room ids while a Dream-House tour is active
    this._tourFromUrl = false;

    this.el = {
      btnSave: document.getElementById("btn-save"),
      saveLabel: document.getElementById("btn-save-label"),
      btnHouse: document.getElementById("btn-house"),
      houseCount: document.getElementById("house-count"),
      drawer: document.getElementById("house-drawer"),
      backdrop: document.getElementById("drawer-backdrop"),
      drawerClose: document.getElementById("drawer-close"),
      drawerList: document.getElementById("drawer-list"),
      drawerEmpty: document.getElementById("drawer-empty"),
      shareInput: document.getElementById("share-input"),
      btnCopy: document.getElementById("btn-copy"),
      btnWalk: document.getElementById("btn-walk-house"),
      btnClear: document.getElementById("btn-clear-house"),
      badge: document.getElementById("house-badge"),
      badgeText: document.getElementById("house-badge-text"),
      badgeExit: document.getElementById("house-badge-exit"),
      toast: document.getElementById("toast"),
    };

    this._parseHouseUrl();
    this._bind();
    this._applyStrings();
    i18n.onChange(() => {
      this._applyStrings();
      this.render();
    });
    this.render();
  }

  /* ---------------------------------------------------------- persistence */

  _loadLocal() {
    try {
      const v = JSON.parse(localStorage.getItem(LS_KEY) || "[]");
      return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
    } catch {
      return [];
    }
  }

  _saveLocal() {
    localStorage.setItem(LS_KEY, JSON.stringify(this.ids));
  }

  _parseHouseUrl() {
    try {
      const p = new URLSearchParams(location.search).get("house");
      if (!p) return;
      const valid = new Set(this.deps.getRooms().map((r) => r.id));
      const chain = [...new Set(p.split(",").map((s) => s.trim()))].filter((id) => valid.has(id));
      if (chain.length >= 2) {
        this.tourChain = chain;
        this._tourFromUrl = true;
      }
    } catch {
      /* malformed URL — ignore */
    }
  }

  /* ---------------------------------------------------------- bindings */

  _bind() {
    this.el.btnSave.addEventListener("click", () => this.toggleSave());
    this.el.btnHouse.addEventListener("click", () => this.toggleDrawer());
    this.el.drawerClose.addEventListener("click", () => this.closeDrawer());
    this.el.backdrop.addEventListener("click", () => this.closeDrawer());
    this.el.btnCopy.addEventListener("click", () => this.copyShareLink());
    this.el.btnClear.addEventListener("click", () => {
      this.ids = [];
      this._saveLocal();
      this.render();
      this._toast(i18n.t.house_cleared);
    });
    this.el.btnWalk.addEventListener("click", () => {
      if (this.ids.length < 2) { this._toast(i18n.t.house_need); return; }
      this.closeDrawer();
      this.startTour(this.ids);
    });
    this.el.badgeExit.addEventListener("click", () => this.exitTour());
    this._onKey = (e) => {
      if (e.key !== "Escape") return;
      if (this.drawerOpen()) this.closeDrawer();
    };
    window.addEventListener("keydown", this._onKey);
  }

  _applyStrings() {
    const t = i18n.t;
    this.el.btnHouse.title = t.house;
    this.el.btnCopy.textContent = t.house_share;
    this.el.btnWalk.textContent = t.house_start;
    this.el.btnClear.textContent = t.house_clear;
    this.el.shareInput.value = this.ids.length ? this.shareUrl() : "";
  }

  /* ---------------------------------------------------------- collection */

  hasRoom(id) { return this.ids.includes(id); }

  toggleSave(id) {
    const roomId = id ?? this._currentRoomId();
    if (!roomId) return;
    if (this.hasRoom(roomId)) {
      this.ids = this.ids.filter((x) => x !== roomId);
      this._saveLocal(); this.render();
      this._toast(i18n.t.removed_toast);
    } else {
      this.ids.push(roomId);
      this._saveLocal(); this.render();
      this._toast(i18n.t.saved_toast);
    }
  }

  removeRoom(id) {
    this.ids = this.ids.filter((x) => x !== id);
    this._saveLocal();
    this.render();
  }

  shareUrl() {
    const base = location.origin + location.pathname;
    return this.ids.length ? `${base}?house=${this.ids.join(",")}` : base;
  }

  async copyShareLink() {
    const url = this.shareUrl();
    this.el.shareInput.value = url;
    try {
      await navigator.clipboard.writeText(url);
      this._toast(i18n.t.house_copied);
    } catch {
      this.el.shareInput.select();
      try { document.execCommand("copy"); this._toast(i18n.t.house_copied); }
      catch { this._toast(i18n.t.house_copy_fail); }
    }
  }

  _currentRoomId() {
    const r = this.deps.getRooms?.()[this._currentIdx ?? -1];
    return r ? r.id : null;
  }

  /** Called by main.js after every room load (updates button/drawer/badge). */
  onRoomChanged(room, idx) {
    this._currentIdx = idx;
    this._currentId = room?.id ?? null;
    this.render();
  }

  /* ---------------------------------------------------------- tour mode */

  tourActive() { return this.tourChain.length >= 2; }

  /** Index of the room the experience should start in (tour chain head). */
  entryIndex(rooms) {
    if (!this.tourActive()) return 0;
    const i = rooms.findIndex((r) => r.id === this.tourChain[0]);
    return i >= 0 ? i : 0;
  }

  startTour(chain) {
    if (!chain || chain.length < 2) { this._toast(i18n.t.house_need); return; }
    this.tourChain = [...chain];
    this._tourFromUrl = false;
    this._applyTourUrl();
    this.deps.onRoutesChanged();
    const rooms = this.deps.getRooms();
    const idx = this.entryIndex(rooms);
    this.render();
    this.deps.onGotoRoom(idx);
  }

  exitTour() {
    if (!this.tourActive()) return;
    this.tourChain = [];
    this._tourFromUrl = false;
    this._applyTourUrl();
    this.deps.onRoutesChanged();
    this.render();
  }

  _applyTourUrl() {
    const url = new URL(location.href);
    if (this.tourActive() && !this._tourFromUrl) {
      url.searchParams.set("house", this.tourChain.join(","));
    } else if (this._tourFromUrl || !this.tourActive()) {
      url.searchParams.delete("house");
    }
    history.replaceState(null, "", url);
  }

  /** Portal targets while touring (delegates to portals.js). */
  houseRoutes(rooms, currentIndex) {
    return computeHouseRoutes(rooms, currentIndex, this.tourChain);
  }

  /* ---------------------------------------------------------- drawer ui */

  drawerOpen() { return this.el.drawer.classList.contains("open"); }

  toggleDrawer() { this.drawerOpen() ? this.closeDrawer() : this.openDrawer(); }

  openDrawer() {
    this.el.shareInput.value = this.ids.length ? this.shareUrl() : "";
    this.el.drawer.classList.add("open");
    this.el.backdrop.classList.add("open");
  }

  closeDrawer() {
    this.el.drawer.classList.remove("open");
    this.el.backdrop.classList.remove("open");
  }

  render() {
    const rooms = this.deps.getRooms ? this.deps.getRooms() : [];
    const byId = new Map(rooms.map((r) => [r.id, r]));
    const L = i18n.lang;

    // save chip
    const saved = this._currentId ? this.hasRoom(this._currentId) : false;
    this.el.btnSave.classList.toggle("saved", saved);
    this.el.saveLabel.textContent = saved ? i18n.t.saved : i18n.t.save_room;

    // house chip count
    this.el.houseCount.textContent = String(this.ids.length);
    this.el.houseCount.classList.toggle("none", this.ids.length === 0);

    // drawer list
    const list = this.el.drawerList;
    list.innerHTML = "";
    this.ids.forEach((id, i) => {
      const r = byId.get(id);
      if (!r) return;
      const item = document.createElement("div");
      item.className = "house-item";
      item.innerHTML = `
        <span class="house-num">${i + 1}</span>
        <img class="house-thumb" src="${r.preview}" alt="">
        <div class="house-meta">
          <div class="house-name">${r.name[L] || r.name.en}</div>
          <div class="house-type">${i18n.t["type_" + r.room_type] || r.room_type.replace(/_/g, " ")}</div>
        </div>
        <button class="house-remove" title="${i18n.t.remove_room}" aria-label="${i18n.t.remove_room}">×</button>`;
      item.querySelector(".house-remove").addEventListener("click", () => this.removeRoom(id));
      list.appendChild(item);
    });
    this.el.drawerEmpty.classList.toggle("hud-hidden", this.ids.length > 0);
    this.el.shareInput.value = this.ids.length ? this.shareUrl() : "";

    // tour badge + mode-bar lock
    const modeBar = document.getElementById("mode-bar");
    if (modeBar) modeBar.classList.toggle("tour-disabled", this.tourActive());
    if (this.tourActive()) {
      this.el.badge.classList.remove("hud-hidden");
      this.el.badgeText.textContent = i18n.t.house_badge(this.tourChain.length);
      const hint = document.getElementById("mode-hint");
      if (hint) hint.textContent = i18n.t.house_hint;
    } else {
      this.el.badge.classList.add("hud-hidden");
    }
  }

  /* ---------------------------------------------------------- toast */

  _toast(msg) {
    const el = this.el.toast;
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => el.classList.remove("show"), 2400);
  }
}
