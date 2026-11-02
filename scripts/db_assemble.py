#!/usr/bin/env python3
"""
PANODROME — Phase 2.5/3 DB assembly
===================================
One-shot curation pass over data/rooms_db.json:

  1. Portal calibration  — apply VLM-verified door fractions to all 18 rooms
     (castle cellar / cabin / abchurch / chapel-royal keep a single portal:
     only one real passage exists) and re-anchor positions on the depth maps.
  2. source_platform      — badges for the 10 PolyHaven rooms.
  3. Persian rewrite      — senior-architect Persian for every room title,
     description and all 52 material hotspots (authentic terminology).
  4. Commerce             — shoppable fields (tier, est. price, swatches)
     for every material hotspot.
  5. Sponsored portals    — 3 gold "Brand Showroom" waypoints.

Writes data/rooms_db.json + public/data/rooms_db.json.
"""
import json
import math
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "rooms_db.json"
DEPLOY = REPO / "public" / "data" / "rooms_db.json"

# ------------------------------------------------------------------ 1. portals
FRACTIONS = {
    # crop-verified per room (anniversary lounge has a single real doorway;
    # laon's 0.116 crop showed a blank wall -> replaced with 0.87)
    "anniversary_lounge": [0.02],
    "photo_studio_loft_hall": [0.025, 0.915],
    "art_studio": [0.058, 0.307],
    "ballroom": [0.335, 0.905],
    "large_corridor": [0.105, 0.375],
    "comfy_cafe": [0.418, 0.685],
    "castle_zavelstein_cellar": [0.11],
    "cabin": [0.355],
    "quadrangle_sunny": [0.49, 0.975],
    "school_hall": [0.594, 0.461],
    "laon_cathedral": [0.628, 0.87],
    "brompton_oratory": [0.226, 0.758],
    "abchurch_st_mary": [0.012],
    "chapel_royal_dublin": [0.0],
    "kings_cross_concourse": [0.435, 0.565],
    "evora_library_hall": [0.624, 0.895],
    "leipzig_festsaal": [0.316, 0.78],
    "masjid_jami_al_huda": [0.01, 0.497],
}
SPONSORED = {  # portal index → gold "Brand Showroom"
    "photo_studio_loft_hall": [0],
    "ballroom": [1],
    "kings_cross_concourse": [0],
}
OLD_WIDTH = {  # keep each room's established door scale
    "anniversary_lounge": (1.15, 2.15), "photo_studio_loft_hall": (1.2, 2.2),
    "art_studio": (1.1, 2.1), "ballroom": (1.5, 2.6), "large_corridor": (1.2, 2.25),
    "comfy_cafe": (1.1, 2.1), "castle_zavelstein_cellar": (1.3, 2.2),
    "cabin": (1.0, 2.05), "quadrangle_sunny": (1.6, 2.4), "school_hall": (1.4, 2.5),
    "laon_cathedral": (1.6, 2.6), "brompton_oratory": (1.5, 2.5),
    "abchurch_st_mary": (1.3, 2.3), "chapel_royal_dublin": (1.3, 2.4),
    "kings_cross_concourse": (2.0, 2.8), "evora_library_hall": (1.1, 2.1),
    "leipzig_festsaal": (1.3, 2.3), "masjid_jami_al_huda": (1.5, 2.4),
}


def equirect_dir(frac, pitch_deg):
    phi = 2 * math.pi * frac
    theta = math.pi / 2 - math.radians(pitch_deg)
    st = math.sin(theta)
    return (-math.cos(phi) * st, math.cos(theta), math.sin(phi) * st)


def depth_at(img, depth_max, frac, pitch):
    w, h = img.size
    px = img.load()
    x = int(frac * (w - 1)) % w
    y = int(((90 - pitch) / 180.0) * (h - 1))
    r, g, _ = px[x, y]
    return ((r * 256 + g) / 65535.0) * depth_max


def rebuild_portals(room):
    img = Image.open(REPO / "public" / room["depth_map"]).convert("RGB")
    cam = room["camera"]
    fracs = FRACTIONS.get(room["id"], [p["fraction"] for p in room["portals"]])
    w, h = OLD_WIDTH.get(room["id"], (1.2, 2.2))
    sponsored = SPONSORED.get(room["id"], [])
    portals = []
    for i, frac in enumerate(fracs):
        frac = float(frac) % 1.0
        dx, dy, dz = equirect_dir(frac, 3.0)
        d = depth_at(img, room["depth_max"], frac, 3.0)
        x = cam["x"] + dx * (d - 0.06)
        y = min(max(cam["y"] + dy * (d - 0.06), 1.0), 2.1)
        z = cam["z"] + dz * (d - 0.06)
        n = (-dx, -dz)
        ln = math.hypot(*n) or 1.0
        pdef = {
            "id": f"{room['id']}_p{i+1}",
            "fraction": round(frac, 4),
            "origin": "ai_vision_door",
            "position": [round(x, 3), round(y, 3), round(z, 3)],
            "normal": [round(n[0] / ln, 3), 0.0, round(n[1] / ln, 3)],
            "width": w,
            "height": h,
            "label": {"en": "Smart Portal", "fa": "درگاه هوشمند"},
        }
        if i in sponsored:
            pdef["sponsored"] = True
        portals.append(pdef)
    return portals


# ------------------------------------------------------------------ 2. Persian
ROOMS_FA = {
    "anniversary_lounge": ("نشیمن کلاسیک سالگرد", "نشیمنی گرم و کلاسیک با فرش دستباف، چراغ ایستاده و نور ملایم پنجره؛ چیدمانی برای نشستن‌های طولانی."),
    "photo_studio_loft_hall": ("راهروی لوفت آفتابی", "راهروی بلند لوفت با کف چوب کهنه، صندلی چسترفیلد سبز و قاب‌گچی سقف؛ نور طبیعی از پنجره‌های تمام‌قد."),
    "art_studio": ("استودیوی نقاشی", "استودیوی نقاش با دیوار منحنی، نقاشی دریایی بزرگ و تیرهای چوبی نمایان؛ فضایی برای خلق اثر."),
    "ballroom": ("سالن رقص ویکتوریایی", "سالن پذیرایی ویکتوریایی با پارکت هندسی، پیانوی سفید و گچ‌بری ظریف؛ شکوه یک دوره کامل."),
    "large_corridor": ("هشتی ورودی بزرگ", "هشتی ورودی مجلل با در دو لته قوسی، بخاری سفالی تزیینی و پارکت هندسی؛ نخستین برداشت از خانه."),
    "comfy_cafe": ("کافه دنج", "کافه‌ای دنج با پارکت بلوط جناغی، لوستر آهنی سیاه و دیوار آجری سفیدی؛ گرمای متریال طبیعی."),
    "castle_zavelstein_cellar": ("سرداب قلعه زاول‌اشتاین", "سرداب سنگی قلعه با طاق آهنگ، کف سنگ لایی و روزنه‌های عمیق؛ خنکی و سکوت سنگ."),
    "cabin": ("اتاق کلبه جنگلی", "اتاق کلبه‌ای در دل جنگل با موکت طرح‌دار، سقف منحنی و آینه چوب‌قاب؛ گرمای چوب همه‌جا هست."),
    "quadrangle_sunny": ("حیاط مرکزی کالج", "حیاط مرکزی کالج با مسیر آجری جناغی، باغ‌بند شاخ‌وبرگ و آلاچیقه چوبی؛ معماری و طبیعت دست‌به‌دست هم."),
    "school_hall": ("تالار مدرسه قدیمی", "تالار اجتماعات مدرسه با سکوی چوبی، قوس پیشانه و سقف بتنی در اکسپوز؛ سادگی صادقانه."),
    "laon_cathedral": ("نیایشگاه کلیسای جامع لان", "نیایشگاه گوتیک قرن دوازدهم؛ ستون‌های دسته‌ای، طاق‌های شش‌پاره و نور رنگین روزنه‌های بلند."),
    "brompton_oratory": ("نیایشگاه برومپتون", "نیایشگاه باروک ایتالیایی در قلب لندن؛ ستون‌های مرمر رنگین، گنبد طلاکاری و نور روشن‌خانه."),
    "abchurch_st_mary": ("کلیسای سنت‌مری آبچرچ", "شاهکار جمع‌وجور کریستوفر رن؛ گنبد نقاشی‌شده بر فراز محراب طلایی و چوب‌آرایی گرم."),
    "chapel_royal_dublin": ("نیایشگاه سلطنتی قلعه دوبلین", "نیایشگاه سلطنتی به سبک احیای گوتیک؛ گنبد چوبی سله‌ای، شیشه‌های رنگی و تورهای نشان‌دار."),
    "kings_cross_concourse": ("سالن غربی ایستگاه کینگز کراس", "قوس فولادی جان مک‌آسلان (۲۰۱۲)؛ سازه مشبک تک‌گشاد بزرگ‌ترین سقف ایستگاهی اروپا."),
    "evora_library_hall": ("تالار کتابخانه عمومی اورا", "تالار نمایشگاهی سفید و مینیمال با طاق‌های پیوسته و دیوار زرد شاخص؛ نور تنها تزیین فضا."),
    "leipzig_festsaal": ("تالار خانه شهری لایپزیگ", "تالارهای شهری رنسانس ۱۵۵۶؛ سقف چوبی کنده‌کاری، سنگ‌کاری درگاه‌ها و شکوه دوره بازرگانی."),
    "masjid_jami_al_huda": ("مسجد جامع الحدا", "مسجد جامع روستایی؛ گنبد مرکزی، قوس‌های جناغی و محراب کاشی‌کار زیر نور ملایم سقف."),
}

HOTSPOTS_FA = {
    "anniversary_lounge": [
        ("فرش هندسی دستباف", "فرشی بزرگ و پررنگ با نقشه هندسی به رنگ‌های لاکی، مشکی و بژ؛ قاب اصلی چیدمان نشیمن."),
        ("میزجانبی چوب گردو", "کابینت چوب گردوی تیره با درب‌های قاب‌دار و پوشش پلی‌ور صیقلی؛ سطحی برای نمایش گل و شیء تزیینی."),
    ],
    "photo_studio_loft_hall": [
        ("کف تخته چوب کهنه", "کف چوب بلوط کهنه با پوشش تیره و پارگی طبیعی؛ زیر نور پنجره بافت چوب دیده می‌شود."),
        ("صندلی چسترفیلد چرمی سبز", "صندلی راحتی سبز به سبک چسترفیلد با دکمه‌دوزی و بازوهای غلتکی؛ قطعه امضای فضا."),
        ("قاب‌گچی سقف", "گچ‌کاری تزیینی سقف با قاب‌بندی کلاسیک؛ جزئیاتی که ارتفاع فضا را شعرگونه نشان می‌دهد."),
    ],
    "art_studio": [
        ("دیوارنگار دریایی", "نقاشی پانورامیک غروب دریا نصب‌شده روی دیوار منحنی؛ لبه بوم مسیر دید را می‌شکند."),
        ("تیرهای منحنی سقف", "تیرهای چوبی قوسی نمایان که انحنای سقف را دنبال می‌کنند؛ سازه در نقش دکور."),
        ("کاشی‌های بزرگ خاکستری", "کف سرامیک فرمت‌بزرگ خاکستری روشن با بندکشی ظریف؛ بستری بی‌ادعا برای آثار هنری."),
    ],
    "cabin": [
        ("موکت طرح‌دار سراسری", "موکت از دیوار تا دیوار با نقشه هندسی مات؛ جاذب صدا و گرم زیر پا."),
        ("پنل‌های فرورفته سقف", "پنل‌های منحنی فرورفته سقف با نور مخفی؛ عمق دادن به سقف با نورپردازی غیرمستقیم."),
        ("آینه چوب‌قاب رومیزی", "آینه بزرگ چوب‌قاب روی کمودی چوبی؛ انعکاس نور و دوبرابر کردن اتاق."),
    ],
    "quadrangle_sunny": [
        ("مسیر آجری جناغی", "مسیر پیاده‌رو آجری با چیدمان جناغی؛ اجرای ظریفی که قدم‌ها را آرام می‌کند."),
        ("باغ‌بند ممرز هرس‌شده", "دیوار سبز ممرزها با هرس منظم به‌صورت باغ‌بند؛ مرز نرم معماری و طبیعت."),
        ("آلاچیقه چوبی مرکزی", "آلاچیقه چوبی تیره با سقف شیبدار در انتهای محور؛ نقطه اتکای منظر."),
    ],
    "school_hall": [
        ("کف سکوی چوبی", "سکوی وسیع با تخته‌های چوبی روشن؛ انتخاب آکوستیک و ضدخش برای صحنه."),
        ("قوس پیشانه چوبی", "قوس گشاد چوبی جداکننده صحنه و سالن؛ لبه‌ی نرم بین بازیگر و تماشاگر."),
        ("سقف بتنی در اکسپوز", "سقف بتنی خام با تیرهای تیره‌رنگ؛ صداقت ساختاری به سبک بروتالیسم صادق."),
    ],
    "comfy_cafe": [
        ("پارکت بلوط جناغی", "پارکت بلوط روشن با چیدمان جناغی؛ کلاسیک‌ترین الگوی کف که فضا را گرم و رسمی نشان می‌دهد."),
        ("لوستر حلقه‌ای آهنی", "لوستر مجسمه‌وار با اسکلت آهنی سیاه؛ نور گرم متمرکز روی میزها."),
        ("دیوار آجری سفیدی", "بخشی از دیوار با آجر سفیدی‌شده نمایان؛ بافت روستیک با بندکشی سنتی."),
    ],
    "large_corridor": [
        ("در دو لته قوسی", "در چوبی تیره دو لته با قوس جناغی و شیشه مشبک؛ ورودی باشکوه هشتی."),
        ("بخاری سفالی تزیینی", "بخاری سفالی قدیمی با نقش برجسته؛ گرمایش و دکور در یک جنس."),
        ("پارکت هندسی", "پارکت با نقشه هندسی روشن و متوسط؛ چیدمانی که مسیر را دنبال می‌کند."),
    ],
    "ballroom": [
        ("پارکت هندسی چندرنگ", "پارکت با نقشه هندسی پیچیده از چوب‌های کنتراست؛ زیر نور لوستر مثل جواهر می‌درخشد."),
        ("پیانوی سفید", "پیانوی دیواره سفید برق‌افتاده در یک‌سوی سالن؛ قطعه امضای فضای پذیرایی."),
    ],
    "castle_zavelstein_cellar": [
        ("روزنه سنگی قوس‌دار", "روزنه‌ای کوچک در دل دیوار سنگی قطور؛ پرتو متمرکز نور در تاریکی سرداب."),
        ("طاق آهنگ سنگی", "طاق آهنگ پیوسته از سنگ‌های ناصاف؛ ریتم و بافتی که قدمت بنا را می‌گوید."),
        ("کف سنگ لایی", "کف از سنگ لایی‌های بزرگ و نامنظم با اختلاف رنگ طبیعی؛ سادگی صادقانه قرون‌وسطا."),
    ],
    "laon_cathedral": [
        ("پرده محراب طلاکاری‌شده", "پرده چوبی عظیم با منبت‌کاری و ورقه طلا و شیشه‌های رنگی؛ جداسازی قدسی و عرفی."),
        ("کف سنگ تیره پولیش", "اسلب‌های سنگ تیره با پولیش آینه‌ای؛ بازتاب نور روزنه‌ها روی کف."),
        ("روزنه گلی گوتیک", "پنجره گلی با توری‌کاری هندسی و شیشه رنگی؛ شاهکار نور و هندسه گوتیک."),
    ],
    "brompton_oratory": [
        ("پارکت جناغی", "پارکت چوب پولیش‌شده با چیدمان جناغی؛ زمینه گرم زیر ستون‌های مرمر."),
        ("گنبد صندوقه‌کاری‌شده", "گنبد مرکزی با صندوقه‌های عمیق و نقاشی‌های فرسکو؛ حلقه نور از روشن‌خانه."),
        ("منبر منبت‌کاری‌شده", "منبر باروک با سایبان منبت‌کاری‌شده و پلکان چوبی؛ جزئیات اجرایی بی‌نظیر."),
    ],
    "abchurch_st_mary": [
        ("محراب چوبی منبت‌کاری", "پیشانی محراب از چوب تیره با منبت‌کاری، ستون‌های کرنتی و ورقه طلا؛ قطعه مرکزی محراب."),
        ("کف سنگ یادبوددار", "اسلب‌های سنگی با کتیبه‌های یادبودی تیره؛ لایه لایه تاریخ زیر پا."),
        ("طاق بشکه‌ای نقاشی‌شده", "طاق بشکه‌ای با نقاشی تاریخی بزرگ و مدالین‌های گچی."),
    ],
    "chapel_royal_dublin": [
        ("کف شطرنجی مرمر", "چیدمان شطرنجی کاشی مرمر سیاه و سفید؛ قدرتمندترین برداشت اولیه فضا."),
        ("تور چوبی منبت‌کاری", "تور چوبی طبقه دوم با منبت‌کاری عظیم؛ چوب به جای سنگ."),
        ("طاق دنده‌دار گچی", "طاق گچی با دنده‌های متقاطع و کلیدکارهای تزیینی؛ سبک احیای گوتیک."),
    ],
    "kings_cross_concourse": [
        ("سقف فولادی مشبک", "سازه تک‌گشاد با الگوی مشبک هندسی؛ مهندسی در نقش شعر."),
        ("نمای آجری ویکتوریایی", "بنای اصلی ایستگاه با آجر قرمز و پنجرهای قوسی بزرگ؛ دیالوگ دو دوره."),
        ("کف سنگ تیره پولیش", "کاشی‌های سنگ تیره با بندکشی مشبک ظریف؛ بستری آرام برای جمعیت."),
    ],
    "evora_library_hall": [
        ("سکوی چوبی منحنی", "سکوی چوبی نرم و منحنی در مرکز تالار؛ ساده‌ترین بستر ممکن برای نمایش اثر."),
        ("دیوار زرد شاخص", "دیوار زرد اشباع به‌عنوان تنها عنصر رنگی؛ انتخاب رنگی شجاعانه گالری‌وار."),
        ("طاق بشکه‌ای تزیینی", "طاق بشکه‌ای با قاب‌های ظریف گچی و نقاشی‌های محو؛ سنگینی سقف در قالب سبک."),
    ],
    "leipzig_festsaal": [
        ("شومینه سنگی باروک", "شومینه سنگی با نقش‌برجسته و قرنیز پیچان؛ مرکز گرمایش و جلب توجه تالار."),
        ("کف سنگ فرمت‌بزرگ", "اسلب‌های سنگی نامنظم با ته‌رنگ خاکستری و بژ؛ کهنگی محترمانه."),
        ("در دو لته چوبی قوسی", "درب چوبی سنگین با قوس بالا و شیشه‌های بیضی؛ درگاه رسمی تالار."),
    ],
    "masjid_jami_al_huda": [
        ("محراب و دیوار خوش‌نویسی", "دیوار سنگی تیره با محراب قوسی و خوش‌نویسی آبی و طلایی؛ قبله و قطعه مرکزی نمازخانه."),
        ("ستون‌های مرمر پولیش", "ستون‌های استوانه‌ای با مرمر خرمایی پولیش‌شده؛ نظم و ایستایی فضای گنبددار."),
        ("کف بازتاب سنگی", "کف مرمر روشن یا تراتزو با پولیش آینه‌ای؛ بازتاب نور گنبد روی زمین."),
    ],
}

# ------------------------------------------------------------------ 3. commerce
# category → (tier, price, swatches) — honest ballpark estimates, marked ≈
CAT_COMMERCE = {
    "wood": ("premium", "from $85/m²", ["#c8a06a", "#8a5a33", "#e2cba8"]),
    "stone": ("premium", "from $95/m²", ["#c6cbd6", "#9aa3ad", "#e8e2d5"]),
    "metal": ("standard", "from $40/m²", ["#9fd4e8", "#7d8fa3", "#4c5560"]),
    "glass": ("signature", "from $220/m²", ["#7fe3f2", "#bcd9e8", "#eef7fb"]),
    "textile": ("standard", "from $35/m²", ["#f0a7c8", "#b4638f", "#6e2f4e"]),
    "ceramic": ("premium", "from $60/m²", ["#8adfd0", "#5fbfb2", "#e8f5f2"]),
    "lighting": ("signature", "from $480/set", ["#ffe08a", "#ffd24d", "#fff3c4"]),
    "concrete": ("standard", "from $28/m²", ["#aab2bd", "#8b929c", "#cdd2d9"]),
    "brick": ("standard", "from $24/m²", ["#e2917a", "#b05e46", "#e8d9c2"]),
    "plaster": ("standard", "from $18/m²", ["#e8dcc8", "#cfc2ab", "#f6efe3"]),
    "vegetation": ("standard", "from $15/m²", ["#a4e6a0", "#6cbf68", "#dff5dd"]),
    "other": ("premium", "inquire", ["#a78bfa", "#7c5cd6", "#d6c8f5"]),
}
SWATCH_NAMES = {
    "wood": (["Golden Oak", "Smoked Oak", "Natural Ash"], ["بلوط طلایی", "بلوط دودی", "خاکستر طبیعی"]),
    "stone": (["Silver Grey", "Basalt", "Ivory"], ["نقره‌ای", "بازالت", "کرم استخوانی"]),
    "textile": (["Rose Bouclé", "Berry Velvet", "Plum Wool"], ["بوکله گلبهی", "مخمل توت‌فرنگی", "پشم بادمجانی"]),
    "lighting": (["Warm 2700K", "Amber 2500K", "Soft 3000K"], ["گرم ۲۷۰۰K", "کهربایی ۲۵۰۰K", "ملایم ۳۰۰۰K"]),
    "glass": (["Clear Low-iron", "Bronze Tint", "Frosted"], ["شفاف کم‌آهن", "برنزه", "مات اسیدی"]),
    "ceramic": (["Mint Ceramic", "Deep Teal", "Bone China"], ["کاشی نعنایی", "فیروزه‌ای تیره", "استخوانی"]),
    "brick": (["Terracotta", "Clinker Red", "Whitewash"], ["سفالی", "قرمز کلوینکر", "سفیدکاری"]),
}
CURATED_COMMERCE = {
    # room → {hotspot_index: (tier, price)} — refine the auto values
    "comfy_cafe": {0: ("signature", "from $128/m²")},
    "brompton_oratory": {0: ("signature", "from $145/m²")},
    "ballroom": {0: ("signature", "from $160/m²")},
    "masjid_jami_al_huda": {2: ("signature", "from $175/m²")},
    "kings_cross_concourse": {2: ("premium", "from $110/m²")},
}


def add_commerce(room):
    cur = CURATED_COMMERCE.get(room["id"], {})
    for i, h in enumerate(room.get("hotspots", [])):
        cat = h.get("material_category", "other")
        tier, price, swatches = CAT_COMMERCE[cat]
        if i in cur:
            tier, price = cur[i]
        en_names, fa_names = SWATCH_NAMES.get(cat, (["Option A", "Option B", "Option C"], ["گزینه ۱", "گزینه ۲", "گزینه ۳"]))
        h["commerce"] = {
            "brand": "Panodrome Showcase",
            "tier": tier,
            "price": price,
            "swatches": swatches,
            "swatch_names": {"en": en_names, "fa": fa_names},
            "cta": "inquire",
        }


# ------------------------------------------------------------------ main
def main():
    db = json.load(open(DB))
    for room in db["rooms"]:
        rid = room["id"]

        # portals — calibrated fractions + depth-anchored positions
        room["portals"] = rebuild_portals(room)

        # platform badge for the original PolyHaven set
        if "source_platform" not in room:
            room["source_platform"] = "PolyHaven"

        # Persian rewrite
        if rid in ROOMS_FA:
            name_fa, desc_fa = ROOMS_FA[rid]
            room["name"]["fa"] = name_fa
            room["description"]["fa"] = desc_fa

        hs_fa = HOTSPOTS_FA.get(rid)
        if hs_fa:
            for i, h in enumerate(room.get("hotspots", [])):
                if i < len(hs_fa):
                    h["title"]["fa"] = hs_fa[i][0]
                    h["desc"]["fa"] = hs_fa[i][1]

        # commerce on every material hotspot
        add_commerce(room)

    DB.write_text(json.dumps(db, indent=2, ensure_ascii=False) + "\n")
    DEPLOY.write_text(json.dumps(db, indent=2, ensure_ascii=False) + "\n")

    n_hot = sum(len(r.get("hotspots", [])) for r in db["rooms"])
    n_comm = sum(1 for r in db["rooms"] for h in r.get("hotspots", []) if "commerce" in h)
    n_spon = sum(1 for r in db["rooms"] for p in r["portals"] if p.get("sponsored"))
    print(f"rooms={len(db['rooms'])} hotspots={n_hot} commerce={n_comm} sponsored_portals={n_spon}")
    for r in db["rooms"]:
        print(f"  {r['id']:26} portals={[p['fraction'] for p in r['portals']]} plat={r['source_platform']}")


if __name__ == "__main__":
    main()
