/**
 * PANODROME — i18n (English-first + full RTL Persian)
 * All static UI strings live here; room metadata comes bilingual from rooms_db.json.
 */
export const STRINGS = {
  en: {
    intro_tag: "Walk through architecture.",
    intro_sub: "Real 360° photographs turned into walkable 3D rooms. Step through glowing portals and drift between spaces that share a mood, a purpose, or nothing at all.",
    enter: "Enter Panodrome",
    intro_hint: "WASD / drag / scroll · headphones recommended",
    loading: "Weaving the room…",
    mode_label: "Portal mode",
    mode_architect: "Architect",
    mode_type: "Room Type",
    mode_style: "Style",
    mode_random: "Random",
    mode_hint: {
      architect: "A curated walk through all ten rooms, in sequence.",
      room_type: "Portals lead to rooms of the same type.",
      style: "Portals follow matching style & materials.",
      random: "Let go — portals lead anywhere.",
    },
    walk: "HOLD TO WALK",
    help_title: "How to walk",
    help_move: "walk with real depth",
    help_drag: "hold button",
    help_scroll: "glide forward / back",
    help_look: "look around",
    help_portal: "Click a glowing portal — or walk straight into it.",
    help_hotspot: "Hover the pulsing dots to inspect materials.",
    room_of: (i, n) => `Room ${i} / ${n}`,
    by: "by",
    license_cc0: "CC0",
    portal_label: "Smart Portal",
    portal_to: "leads to",
    reason: {
      architect: "curated walk",
      room_type: "same room type",
      style: "style match",
      random: "serendipity",
    },
    inspector_chip: "AI INSPECTOR",
    next_prefetch: "Scouting next room…",
  },
  fa: {
    intro_tag: "در معماری قدم بزن.",
    intro_sub: "عکس‌های واقعی ۳۶۰ درجه که به اتاق‌های سه‌بعدیِ قابل‌قدم‌زدن تبدیل شده‌اند. از درگاه‌های نورانی عبور کن و بین فضاهایی سرگردان شو که حال‌وهوایی مشترک، کاربردی مشترک، یا هیچ چیز مشترکی ندارند.",
    enter: "ورود به پانودروم",
    intro_hint: "WASD / کشیدن / اسکرول · استفاده از هدفون توصیه می‌شود",
    loading: "در حال بافتن اتاق…",
    mode_label: "حالت درگاه",
    mode_architect: "معمار",
    mode_type: "نوع فضا",
    mode_style: "سبک",
    mode_random: "تصادفی",
    mode_hint: {
      architect: "گشت‌وگذاری برنامه‌ریزی‌شده در هر ده فضا، به‌ترتیب.",
      room_type: "درگاه‌ها به فضاهایی از همان نوع می‌رسند.",
      style: "درگاه‌ها از سبک و متریال مشترک پیروی می‌کنند.",
      random: "خودت را رها کن — درگاه‌ها به هرجایی می‌رسند.",
    },
    walk: "برای قدم‌زدن نگه دار",
    help_title: "چطور قدم بزنیم",
    help_move: "قدم بزن با عمق واقعی",
    help_drag: "نگه‌داشتن دکمه",
    help_scroll: "سر خوردن به جلو / عقب",
    help_look: "نگاه کردن اطراف",
    help_portal: "روی درگاه نورانی کلیک کن — یا مستقیم داخلش قدم بگذار.",
    help_hotspot: "نقطه‌های تپنده را برای بررسی متریال هاور کن.",
    room_of: (i, n) => `اتاق ${i} از ${n}`,
    by: "سازنده",
    license_cc0: "CC0",
    portal_label: "درگاه هوشمند",
    portal_to: "می‌رسد به",
    reason: {
      architect: "گشت برنامه‌ریزی‌شده",
      room_type: "هم‌نوع فضا",
      style: "سبک مشترک",
      random: "تصادف",
    },
    inspector_chip: "بازرس هوشمند",
    next_prefetch: "در حال رصد اتاق بعدی…",
  },
};

export const i18n = {
  lang: "en",
  listeners: [],
  get t() {
    return STRINGS[this.lang];
  },
  setLang(lang) {
    this.lang = STRINGS[lang] ? lang : "en";
    document.documentElement.lang = this.lang;
    document.documentElement.dir = this.lang === "fa" ? "rtl" : "ltr";
    this.listeners.forEach((fn) => fn(this.lang));
  },
  onChange(fn) {
    this.listeners.push(fn);
  },
};
