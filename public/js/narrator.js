/**
 * PANODROME — AI Architectural Narrator (Phase 3)
 *
 * Reads room and material analyses aloud with the browser's
 * SpeechSynthesis engine, auto-selecting a natural EN or FA voice.
 * Used by the hotspot card, the room creator card and portal cards.
 */
import { i18n } from "./i18n.js";

export class Narrator {
  constructor() {
    this.speaking = false;
    this._utter = null;
    this._voices = [];
    this._warned = false;
    this.onStateChange = null;

    if ("speechSynthesis" in window) {
      const load = () => { this._voices = window.speechSynthesis.getVoices() || []; };
      load();
      window.speechSynthesis.onvoiceschanged = load;
      window.speechSynthesis.addEventListener?.("voiceschanged", load);
    }
  }

  get available() {
    return "speechSynthesis" in window;
  }

  _pickVoice(lang) {
    const want = lang === "fa" ? "fa" : "en";
    const list = this._voices.length
      ? this._voices
      : (window.speechSynthesis ? window.speechSynthesis.getVoices() || [] : []);
    // exact locale first, then any voice of the language family
    let v = list.find((x) => x.lang?.toLowerCase().startsWith(want + "-"));
    if (!v) v = list.find((x) => x.lang?.toLowerCase().startsWith(want));
    // prefer higher-quality "natural"/"google" voices when present
    const sameLang = list.filter((x) => x.lang?.toLowerCase().startsWith(want));
    const nice = sameLang.find((x) => /natural|google|neural|premium/i.test(x.name));
    return nice || v || null;
  }

  /**
   * Speak `text` in the current UI language (or override with lang).
   * @param {string} text
   * @param {{lang?: string, onEnd?: Function}} [opts]
   */
  speak(text, opts = {}) {
    if (!this.available) {
      if (!this._warned) {
        this._warned = true;
        console.warn("[narrator] SpeechSynthesis unavailable in this browser");
      }
      return false;
    }
    const lang = opts.lang || i18n.lang;
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    if (!clean) return false;

    this.stop();
    const u = new SpeechSynthesisUtterance(clean);
    const voice = this._pickVoice(lang);
    if (voice) u.voice = voice;
    u.lang = lang === "fa" ? "fa-IR" : "en-US";
    u.rate = lang === "fa" ? 0.95 : 1.0;
    u.pitch = 1.0;
    u.onstart = () => { this.speaking = true; this.onStateChange?.(true); };
    const done = () => {
      this.speaking = false;
      this._utter = null;
      this.onStateChange?.(false);
      opts.onEnd?.();
    };
    u.onend = done;
    u.onerror = done;
    this._utter = u;
    window.speechSynthesis.speak(u);
    return true;
  }

  stop() {
    if (!this.available) return;
    window.speechSynthesis.cancel();
    this.speaking = false;
    this.onStateChange?.(false);
  }
}
