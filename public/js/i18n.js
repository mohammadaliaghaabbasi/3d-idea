/**
 * PANODROME — Stage 1 · i18n (EN / FA-RTL)
 * Authentic Persian architectural tone · Vazirmatn typography.
 */

const STRINGS = {
  en: {
    tagline: "The spatial & living architecture collection — walk through real interiors in 360°.",
    intro_sub: "Six curated spaces · Pure optical walk · Zero distortion",
    intro_hint: "Drag to look around · Scroll or double-tap to move forward",
    enter: "Enter Panodrome",
    credit: "360° panoramas · PolyHaven · CC0",
    nav_prev: "Previous space",
    nav_next: "Next space",
    hint: "Scroll or double-tap to move forward",
    reset_view: "Step back to centre",
    fullscreen: "Fullscreen",
    walk_f: "Move forward",
    walk_b: "Step back",
    enter_room: "Enter",
    loading: "Preparing the space…",
    lang_btn: "فا",
    counter: (i, n) => `(${i} of ${n})`,
  },
  fa: {
    tagline: "مجموعه‌ معماریِ فضایی و زیست‌پذیر — در فضاهای واقعی ۳۶۰ درجه قدم بزنید.",
    intro_sub: "شش فضای منتخب · گشت‌وگذار نوریِ خالص · بدون هیچ اعوجاجی",
    intro_hint: "برای گردش بکشید · برای جلو رفتن اسکرول کنید یا دو بار ضربه بزنید",
    enter: "ورود به پانودروم",
    credit: "پانورامای ۳۶۰ درجه · پلی‌هیون · CC0",
    nav_prev: "فضای قبلی",
    nav_next: "فضای بعدی",
    hint: "برای جلو رفتن اسکرول کنید یا دو بار ضربه بزنید",
    reset_view: "بازگشت به مرکز فضا",
    fullscreen: "نمایش تمام‌صفحه",
    walk_f: "حرکت به جلو",
    walk_b: "حرکت به عقب",
    enter_room: "ورود",
    loading: "در حال آماده‌سازی فضا…",
    lang_btn: "EN",
    counter: (i, n) => `(${faDigits(i)} از ${faDigits(n)})`,
  },
};

function faDigits(s) {
  const map = { "0": "۰", "1": "۱", "2": "۲", "3": "۳", "4": "۴", "5": "۵", "6": "۶", "7": "۷", "8": "۸", "9": "۹" };
  return String(s).replace(/[0-9]/g, (d) => map[d]);
}

class I18n {
  constructor() {
    this.lang = "en";
    this._listeners = new Set();
  }
  get t() { return STRINGS[this.lang]; }
  setLang(lang) {
    if (!STRINGS[lang] || lang === this.lang) return;
    this.lang = lang;
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
    document.body.classList.toggle("fa", lang === "fa");
    this._listeners.forEach((fn) => fn());
  }
  onChange(fn) { this._listeners.add(fn); return () => this._listeners.delete(fn); }
}

export const i18n = new I18n();
export { faDigits };
