/**
 * PANODROME — Commerce engine (Phase 3)
 *
 * Realises the 4-layer business model inside the walkable UI:
 *   1. Shoppable furniture & material hotspots — brand badge, spec tier,
 *      est. price, 2–3 sample swatches and a "View / Inquire" CTA
 *      (card markup lives in hotspots.js; swatch state comes from here).
 *   2. Architect lead-gen — "Request Design / Contact Architect" opens
 *      a project-inquiry drawer prefilled with the room's creator and
 *      portfolio link (no fake backend: the request summary is copied
 *      for the creator's own contact channel).
 *   3. Sponsored golden portals — `"sponsored": true` on portal defs
 *      renders a gold waypoint + "Brand Showroom" badge (portals.js).
 */
import { i18n } from "./i18n.js";

export class Commerce {
  constructor() {
    this.mode = null;          // 'design' | 'product'
    this.room = null;
    this.hotspot = null;
    this.selectedSwatch = 0;

    this.el = {
      backdrop: document.getElementById("inquiry-backdrop"),
      drawer: document.getElementById("inquiry-drawer"),
      title: document.getElementById("inquiry-title"),
      chip: document.getElementById("inquiry-chip"),
      subject: document.getElementById("inquiry-subject"),
      form: document.getElementById("inquiry-form"),
      name: document.getElementById("inq-name"),
      project: document.getElementById("inq-project"),
      budget: document.getElementById("inq-budget"),
      note: document.getElementById("inq-note"),
      submit: document.getElementById("inq-submit"),
      portfolio: document.getElementById("inq-portfolio"),
      copy: document.getElementById("inq-copy"),
      close: document.getElementById("inquiry-close"),
      toast: document.getElementById("toast"),
    };
    this._bind();
    i18n.onChange(() => this._applyStrings());
    this._applyStrings();
  }

  _bind() {
    this.el.close.addEventListener("click", () => this.close());
    this.el.backdrop.addEventListener("click", () => this.close());
    this.el.submit.addEventListener("click", () => this._submit());
    this.el.copy.addEventListener("click", () => this._copySummary());
    this._onKey = (e) => { if (e.key === "Escape" && this.open_) this.close(); };
    window.addEventListener("keydown", this._onKey);
  }

  get open_() { return this.el.drawer.classList.contains("open"); }

  _applyStrings() {
    const t = i18n.t;
    if (!t.inq_title) return;
    this.el.submit.textContent = t.inq_submit;
    this.el.copy.textContent = t.inq_copy;
    this.el.portfolio.textContent = t.inq_portfolio;
    this.el.name.placeholder = t.inq_name;
    this.el.note.placeholder = t.inq_note;
    if (this.mode) this._fill(); // re-localise open drawer
  }

  /**
   * Open the inquiry drawer.
   * @param {'design'|'product'} mode  design = hire the architect,
   *                                   product = material / furniture inquire
   */
  openInquiry(mode, room, hotspot = null) {
    this.mode = mode;
    this.room = room;
    this.hotspot = hotspot;
    this._fill();
    this.el.drawer.classList.add("open");
    this.el.backdrop.classList.add("open");
  }

  close() {
    this.el.drawer.classList.remove("open");
    this.el.backdrop.classList.remove("open");
  }

  _fill() {
    const t = i18n.t, L = i18n.lang;
    const r = this.room;
    if (!r) return;
    const creator = r.attribution?.creator || r.attribution?.source || "—";
    const url = r.attribution?.url || "#";
    this.el.title.textContent =
      this.mode === "design" ? t.inq_title_design : t.inq_title_product;
    this.el.chip.textContent = r.source_platform || r.attribution?.source || "";
    const subj = this.mode === "design"
      ? (r.name?.[L] || r.name?.en || r.id)
      : ((this.hotspot?.title?.[L] || this.hotspot?.title?.en || "") +
         " — " + (r.name?.[L] || r.name?.en || r.id));
    this.el.subject.textContent = subj;
    this.el.portfolio.href = url;
    this.el.portfolio.onclick = (e) => {
      if (url === "#") { e.preventDefault(); this._toast(t.inq_no_portfolio); }
    };
    // project type + budget options
    this.el.project.innerHTML = (t.inq_projects || []).map((p) => `<option>${p}</option>`).join("");
    this.el.budget.innerHTML = (t.inq_budgets || []).map((b) => `<option>${b}</option>`).join("");
  }

  _summary() {
    const L = i18n.lang;
    const r = this.room || {};
    const lines = [
      `${this.mode === "design" ? i18n.t.inq_title_design : i18n.t.inq_title_product}`,
      `${i18n.t.inq_subject}: ${this.el.subject.textContent}`,
      `${i18n.t.inq_creator}: ${r.attribution?.creator || ""} (${r.source_platform || r.attribution?.source || ""})`,
      `${i18n.t.inq_name}: ${this.el.name.value || "—"}`,
      `${i18n.t.inq_project_label}: ${this.el.project.value || "—"}`,
      `${i18n.t.inq_budget_label}: ${this.el.budget.value || "—"}`,
      `${i18n.t.inq_note}: ${this.el.note.value || "—"}`,
    ];
    return lines.join("\n");
  }

  _submit() {
    if (!this.el.name.value.trim()) {
      this.el.name.focus();
      this._toast(i18n.t.inq_need_name);
      return;
    }
    this._copy(true);
    this._toast(i18n.t.inq_done);
    setTimeout(() => this.close(), 900);
  }

  _copy(silent) {
    const text = this._summary();
    const done = () => { if (!silent) this._toast(i18n.t.inq_copied); };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => this._fallbackCopy(text, done));
    } else {
      this._fallbackCopy(text, done);
    }
  }

  _fallbackCopy(text, done) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); done(); } catch (e) { /* ignore */ }
    ta.remove();
  }

  _copySummary() { this._copy(false); }

  _toast(msg) {
    const el = this.el.toast;
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(this._toastT);
    this._toastT = setTimeout(() => el.classList.remove("show"), 2400);
  }
}
