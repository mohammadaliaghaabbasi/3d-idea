# Spark Integration Report — PHASE 4
**Mission:** PANODROME — ENGINE UPGRADE V1.0 · **Date:** 2026-11-04 · **Branch:** `engine-upgrade-v1`
**Subject:** یکپارچه‌سازی ایزولهٔ Spark در صفحهٔ آزمایشی مستقل — طبق حکم مالک، three.js پروداکشن (0.160) **دست‌نخورده**.

> **VERDICT: PASS** — SPZ ما در Spark لود و بیت‌به‌بیت با کرهٔ پانو هم‌راستا رندر شد. صفر خطا.
> صفحهٔ زندهٔ لاب: `public/labs/engine-v1/` (deploy در PHASE 9 → URL آیفون برای مالک)

---

## ۱) معماری ایزوله

| مورد | مقدار |
|---|---|
| شاخه | `engine-upgrade-v1` (جدا از main؛ ادغام فقط پس از رگرسیون سبز) |
| صفحهٔ تست | `public/labs/engine-v1/index.html` — هیچ فایل مشترکی با اپ اصلی ندارد (صرفاً additive) |
| three.js پروداکشن | **0.160 بدون تغییر** — در `/labs/` نسخهٔ پین‌شدهٔ جدا vendored شده |
| نسخه‌های پین‌شدهٔ لاب | **three@0.180.0** (دقیق) + **@sparkjsdev/spark@2.4.0** (دقیق) — بدون CDN، فایل محلی |
| بدون `npm` در runtime | ایمپورت‌مپ محلی: `three` → `vendor/three-0.180.0.module.min.js`، `@sparkjsdev/spark` → `vendor/spark-2.4.0/spark.module.min.js` |

### سه کشف فنی دشوار که حل شد (برای تکرارپذیری)
1. **three 0.180 split-build است:** `three.module.min.js` از `./three.core.min.js` import می‌کند (از r167+) — هر دو باید vendored شوند.
2. **اسپارک `three/addons/postprocessing/Pass.js` را import می‌کند** — ایمپورت‌مپ به `three/addons/` لازم است (Pass.js به‌صورت مجزا vendored شد).
3. **کنوانسیون دوربین three:** `PerspectiveCamera(fov=72)` عمودی است نه افقی (با aspect 2.22 → افقی ~117°) — در مقایسهٔ GT باید درست حساب شود، وگرنه خطای زوم ۲۲٪ مصنوعی تولید می‌کند.

## ۲) نتایج تست SPZ در Spark (headless Chromium WebGL2)

| سنجه | نتیجه |
|---|---|
| لود `cabin_splat.spz` (SPZ **v4 / NGSP**) | ✅ موفق — **338–934 ms** (سرد/گرم) |
| تعداد splat | ✅ **132,349** — دقیقاً همان PLY، صفر جاافتادگی |
| خطاهای console | ✅ **0** (پس از رفع باگ مسابقه‌ای fps در HUD) |
| WebGL2 | ✅ فعال |
| حافظهٔ JS heap | **20–38 MB** (سبک) |
| FPS در ساندباکس headless (SWGL) | 10–50 — **نمایندهٔ موبایل نیست**؛ معیار واقعی = آیفون مالک (چک‌لیست §6) |
| عکس‌های شاهد | `docs/rd-artifacts/engine-v1/phase4_orientation_check.json` + `phase4_composite_quality.json` |

## ۳) اثبات هم‌راستایی هندسی (مهم‌ترین چک PHASE 4)

اسکرین‌شات WebGL اسپارک (کامپوزیت اسپلت روی پانو، دوربین مبدأ) در برابر ground-truth بازنمونه‌گیری‌شده از همان پانورامای ۴K:

| فرضیه | Pearson correlation | نتیجه |
|---|---|---|
| **هم‌راستایی با قرارداد room.js (Δyaw=0, Δpitch=0)** | **0.923** ← بیشینهٔ سراسری | ✅ |
| جابه‌جایی yaw ±90°/180°/±pitch | 0.05–0.27 | رد شد |
| PSNR کامپوزیت vs عکس اصلی | **24.6 dB** | ✅ (اختلاف باقی‌مانده = نرمی گاوسی + ریسمپل) |
| نسبت روشنایی | **0.987** | ✅ |

**معنا:** مختصات SPZ ما (PHASE 1/3) بیت‌به‌بیت همان کرهٔ `SphereGeometry(500,128,96)` تولیدی
room.js است — **هیچ چرخش/آینه‌سازی اصلاحی لازم نیست**. این دقیقاً همان چیزی است که ادعای
معماری چندلایه لازم داشت.

## ۴) حکم VLM (TIER-2 — `glm-5.3-flash`)

> `looks_like_real_photo: true` · `is_upright: true` · `black_hole_regions: false` ·
> `cartoon_low_poly_geometry: false` · اشیا: sofa / round table / picture frame / pillow / backpack / hanging clothes
> کیفیت: **6/10** — «قابل‌باور اما نرم/تار در سطوح، مخصوصاً دیوار چپ» — نرمیِ ذاتی splat؛
> در معماری ما لایهٔ اصلی در سکون، پانوی 4K تیز است.

## ۵) کنترل‌ها و کامپوزیتور (پیش‌نمایش PHASE 5)

- **Drag-look:** Δyaw برابر فرمول (80px × 0.0052 = 0.416 rad ✓) — Pointer Events (لمس + ماوس یکسان).
- **D-pad لمسی:** ۳ کلیک ▲ → حرکت 0.705m در جهت دوربین ✓؛ clamp شعاع امن فعال (SAFE_R=1.3).
- **کراس‌فید:** tween نما-M پایه 350ms؛ sweep قطعی 0→1→0 تست شد (blend=0.576 میانه ثبت شد).
- **مدل کامپوزیت (اصلاح‌شده نسبت به پیش‌نویس اولیه):** پانو **همیشه-opaque** است و اسپلت با alpha
  روی آن fade می‌شود ⇒ حفره‌های disocclusion با پیکسل تقریباًدرستِ پانو **پر می‌شوند نه سیاه**
  (در تست pano=0 لایهٔ خام 24% تیره‌تر بود؛ با پانوی opaque نسبت روشنایی 0.987 شد).

## ۶) باندل و بارگذاری اولیهٔ صفحهٔ لاب

| فایل | raw | gzip |
|---|---|---|
| three 0.180 (module+core, min) | 702 KB | 174 KB |
| Spark 2.4.0 (module.min، شامل worker+wasm inline) | 2,785 KB | 957 KB |
| `cabin_splat.spz` | 1,064 KB | ~1,063 KB (فشرده) |
| **جمع بار اول (بدون پانو ۴K)** | **4.66 MB** | **2.25 MB** |

نکته: وزن اسپارک ۹۵۷KB gz برای موبایل سنگین اما فقط در لاب/حالت-3D بارگذاری می‌شود (lazy در
PHASE 9). گزینهٔ جایگزین سبک‌تر = GaussianSplats3D (§7).

## ۷) مقایسه با گزینهٔ fallback: GaussianSplats3D

| معیار | Spark 2.4.0 | GaussianSplats3D (fallback موقت) |
|---|---|---|
| لایسنس | MIT ✓ | MIT ✓ |
| سازگاری three.js | ≥0.180 (نیازمند نسخهٔ موازی لاب) | **≥0.160 = با پروداکشن فعلی مستقیم** |
| فرمت‌ها | PLY/SPZ v4/SPLAT/KSPLAT/SOG | PLY/SPLAT/KSPLAT (**SPZ نمی‌خواند** → باید SPZ را decode→PLY 32MB یا .splat کنverso کرد) |
| موبایل/سورت | Worker-based، LOD، فربهٔ‌خوبی موبایل | سورت CPU main-thread، سنگین‌تر روی آیفون |
| حجم runtime | ~957KB gz | ~350KB gz |
| وضعیت توسعه | فعال (World Labs، push 2026-10-20) | کند (push 2025-10-19) |

**حکم:** Spark انتخاب نهایی (طبق تصمیم مالک) و اثبات شد. GaussianSplats3D فقط اگر ارتقای نهایی
three پروداکتن به r180+ مانع جدی بیاورد، به‌عنوان نمایشگر موقت با تبدیل فرمت one-shot در نظر
گرفته می‌شود — **در این مأموریت فعال نشد**.

## ۸) چک‌لیست تست آیفون 13 Safari (برای مالک — بعد از deploy PHASE 9)
1. لود `…/panodrome/labs/engine-v1/` روی شبکهٔ واقعی → زمان بارگذاری کامل
2. درگ یک‌انگشتی → نرمی چرخش دوربین
3. دکمه‌های ▲▼◀▶ → راه‌رفتن با پارالاکس واقعی + کراس‌فید بدون پرش
4. FPS ذهنی: آیا هنگام راه‌رفتن رندر ۳۰fps+ می‌ماند؟
5. مصرف باتری/گرما در ۲ دقیقه
6. کراس‌فید 350ms: ghosting قابل‌تحمل است؟ (پارامتر `?fade=` برای تنظیم)

**PHASE 4 VERDICT: PASS** → PHASE 5 (مستندسازی کمی کامپوزیتور + تست ghosting).
