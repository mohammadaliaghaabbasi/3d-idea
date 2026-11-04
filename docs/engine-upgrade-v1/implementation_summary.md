# Implementation Summary — PANODROME ENGINE UPGRADE V1.0
**Date:** 2026-11-04 · **Branch:** `engine-upgrade-v1` (pushed ✓ 306f75e) · **main: دست‌نخورده @ 80aa158**
**Deploy:** زنده ✓ (افزایشی) · **Regression:** purge_smoke **20/20 ALL GREEN**

---

## وضعیت فازها (همگی در این مأموریت اجرا شدند)

| فاز | نتیجه | سند تحویل |
|---|---|---|
| 0 — امنیت و حفاظت پروژه | ✅ PASS | `security_audit.md` + `project_state.md` |
| 1 — تأیید موتور CPU | ✅ PASS (ALL 15 checks) | `cpu_pipeline_verification.md` |
| 2 — ممیزی لایسنس | ✅ PASS (همهٔ اجزای محصول MIT/Apache-2.0) | `license_audit.md` |
| 3 — خط تولید SPZ | ✅ PASS (ALL 16 checks، ۳۰×) | `spz_pipeline_test.md` |
| 4 — یکپارچه‌سازی Spark | ✅ PASS (ایزوله، zero-CDN) | `spark_integration_report.md` |
| 5 — کامپوزیتور | ✅ PASS (+ رفع یک باگ واقعی لایه‌بندی) | `compositor_test.md` |
| 6 — بنچمارک حرکت | ✅ PASS (پروفایل cabin) | `movement_benchmark.md` |
| 7 — برخورد و پلان | ✅ (دیسک SAFE_R داده‌محور) | `recommended_architecture.md` §PHASE 7 |
| 8 — بنچمارک سه‌صحنه‌ای | ✅ PASS (تنظیمات یکسان) | `movement_benchmark.md` §5 |
| 9 — یکپارچه‌سازی پروداکشن | ✅ increasing-deploy زنده؛ **main پاک** | همین سند §زیر |

## اعداد کلیدی موتور (همه از اجرای واقعی امروز)

- موتور CPU: **~۶٫۶–۷٫۱s برای هر پانورامای ۴K** → ۱۳۲,۳۴۹ gaussian → **PLY 32.8MB → SPZ ~1٫۰–۱٫۱MB (۳۰×)** · Peak RAM ~۹۵۵MB · GPU = صفر.
- Round-trip SPZ: دلتای موقعیت ≤ **0.12mm**، رنگ ≈ **0.9/255**، PSNR قبل/بعد **۴۳–۴۵dB**.
- رندر Spark: لود ۳۳۸–۹۱۰ms، **صفر خطای کنسول**، heap ۲۰–۵۰MB، FPS مستقل از فاصلهٔ حرکت.
- هم‌راستایی: correlation هویت **0.758** (لایهٔ خالص اسپلت) / **0.925** (کامپوزیت) — بیت‌به‌بیت همان قرارداد room.js.
- پارالاکس: در 0.75m بودجهٔ ghosting 20.3dB (۲۷٪ پیکسل) فقط در پنجرهٔ ۳۵۰ms؛ VLM: believable+upright در 0.75/1.30m.
- SAFE_R داده‌محور هر ۳ صحنه: **1.30m** (پوستهٔ اندازه‌گیری‌شده ≥ 3.06m).

## تجربهٔ زندهٔ قابل‌تست (برای آیفون مالک)

- **لاب موتور V1.0 (۳ صحنه):** `https://mohammadaliaghaabbasi.github.io/panodrome/labs/engine-v1/`
  - cabin · café · studio (لینک پایین صفحه) · درگ = نگاه · ▲▼◀▶ = قدم‌زدن با پارالاکس واقعی · کراس‌فید ۳۵۰ms
  - پارامترها: `?scene=…&pano=0|1&blend=auto|0|1&offset=…&dir=%2Bx&safeR=…&fade=…`
- **اپ اصلی (بدون هیچ تغییر):** `https://mohammadaliaghaabbasi.github.io/panodrome/` — md5 فایل‌های اصلی زنده = مخزن ✓

## آنچه عمداً انجام نشد (طبق حکم مالک)

1. **three.js پروداکتن ارتقا نیافت** (0.160 می‌ماند؛ 0.180 فقط داخل لاب vendored شد).
2. **هیچ فایل سالم Panodrome حذف/بازنویسی نشد** — تغییرات ۱۰۰% افزایشی در `public/labs/engine-v1/` + اسکریپت‌ها/مستندات جدید.
3. **Spark وارد اپ اصلی نشد** — منتظر تست آیفون مالک (چک‌لیست در spark_integration_report §8).
4. **هیچ مدل محدودی (SHARP/PaGeR/OmniRoam) و هیچ API پولی استفاده نشد.**
5. **گسترش به ۱۰ فضا انجام نشد** — شرط مالک: اول قبولی سه اتاق آزمایشی.

## اقدامات باز (مالک)

1. **🔴 فوری — توکن GitHub:** فعلاً ACTIVE است (scope=repo) و سابقهٔ افشا دارد → Settings → Developer settings → Personal access tokens → **Revoke + توکن جدید** → فقط مقدار `GITHUB_TOKEN` در `.env` عوض شود. (ایجنت نمی‌تواند PAT را باطل کند.)
2. **تست آیفون 13 Safari** روی لاب (چک‌لیست ۶-بندی spark_integration_report §8) → گزارش FPS/ghosting/کراس‌فید.
3. تصمیم ادغام: `engine-upgrade-v1 → main` (PR آماده است) یا ادامهٔ آزمایش در لاب.
4. تنظیم چشمی `fade` (۳۵۰ → ۲۵۰/۵۰۰/۷۰۰) روی آیفون.

## نقشهٔ فایل‌های این مأموریت

```
docs/engine-upgrade-v1/          ← هر ۱۰ سند تحویل + این خلاصه
docs/rd-artifacts/engine-v1/     ← همهٔ شواهد خام (JSONهای فاز ۱/۳/۴/۵/۶/۸ + cabin_splat.spz)
scripts/engine_v1/               ← ۶ اسکریپت تکرارپذیر (verify, license, spz, compositor, benchmark, scene batch)
public/labs/engine-v1/           ← صفحهٔ لاب زنده (vendored spark+three، بدون CDN)
```
