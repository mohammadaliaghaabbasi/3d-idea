# Project State — PHASE 0
**Mission:** PANODROME — ENGINE UPGRADE V1.0 · **Date:** 2026-11-04

---

## 1) توپولوژی مخازن (SSOT)

| مخزن | نقش |
|---|---|
| `mohammadaliaghaabbasi/3d-idea` (private) | **تنها منبع حقیقت** — تمام کد/docs/skills/MEMORY_STATE فقط اینجا ویرایش می‌شود. نسخهٔ کاری: `/home/z/my-project/3d-idea` |
| `mohammadaliaghaabbasi/panodrome` | آینهٔ خروجی deploy (gh-pages) — هرگز مستقیم ویرایش نمی‌شود |
| سایت زنده | `https://mohammadaliaghaabbasi.github.io/panodrome/` |

## 2) وضعیت گیت در شروع این مأموریت

| مورد | وضعیت |
|---|---|
| شاخهٔ فعال پیش از مأموریت | `main` |
| HEAD | `80aa158` — «purge: cartoon GLBs removed… smoke 20/20 ALL GREEN» |
| Working tree | **کاملاً تمیز** (صفر تغییر کامیت‌نشده) — چیزی برای گم‌شدن وجود ندارد |
| شاخهٔ dev این مأموریت | `engine-upgrade-v1` — از `main@80aa158` ساخته شد (تمام فازهای V1.0 اینجا) |
| `main` | دست‌نخورده می‌ماند تا پایان regressions |

### راستی‌آزمایی موارد خواسته‌شده در دستور مالک
1. **کامیت `6b1b51e`** — ✓ موجود در تاریخچه: «stage2.1 TRUE-WALK EVERYWHERE… ALL 134 E2E
   CHECKS GREEN». دوران کارتونی به‌جای حذف، در تاریخچه سالم نگه داشته شد (از طریق purge
   کامیت `80aa158` که فایل‌های سایت را به خط تمیز `0eba439` برگرداند).
2. **شاخهٔ `master-upgrade-WIP`** — ⚠️ **نکتهٔ صادقانه:** چنین شاخه‌ای وجود ندارد و در
   `git branch -a` فقط `main` + `origin/main` هست (هیچ شاخه‌ای هرگز حذف نشده). WIP ناتمامِ
   master-upgrade در واقع به‌صورت **`stash@{0}`** نگهداری شده:
   `On main: master-upgrade-WIP cartoon purge 2026-11-04: 10 procedural GLBs + dollhouse/materials/radar JS + build_all_3d_rooms.py — superseded by open-source R&D mission`
   → این stash مطابق دستور **دست‌نخورده باقی می‌ماند** و بدون تأیید صریح مالک restore نمی‌شود
   (محتوایش همان هندسهٔ کارتونی است که مالک حذفش را خواسته).
3. **حفظ تغییرات کامیت‌نشده** — tree تمیز بود؛ stash و هیچ فایلی حذف/بازنویسی نشد.

## 3) وضعیت سایت زنده (baseline تمیز — بستر این مأموریت)

- ۱۰ اتاق = پانورامای 4K بدون اعوجاج روی `SphereGeometry(500,128,96)` + Floor Waypoints +
  پورتال‌های walk-in + رادار پلان ۲D زنده؛ ۱ ویلای true-3d (`modern_3d_villa.glb`).
- GLB های کارتونی روی دامنهٔ زنده **404** (تأیید post-deploy در doc-14 §0).
- E2E دروازهٔ پاکسازی: `scripts/purge_smoke.sh` → **20/20 ALL GREEN**.

## 4) زیرساخت اجرایی ساندباکس

| منبع | مقدار |
|---|---|
| CPU / RAM | 2 هسته / ~4GB — **بدون GPU** |
| `onnxruntime` | 1.31.1 (CPUExecutionProvider) |
| `opencv-python` / `numpy` | 4.13.0 / 2.1.3 |
| `spz` (nianticlabs, pip) | 1.1.0 — نصب و تست‌شده (۳۰× فشرده‌سازی در doc-14) |
| مدل `dav2_small.onnx` | `/tmp/dav2/dav2_small.onnx` (99MB, onnx-community/Apache-2.0) |
| Node/npm | npm 11.19.1؛ دسترسی به registry.npmjs.org ✓ |

## 5) نقشهٔ فایل‌های کلیدی برای فازهای بعد

| فایل | نقش در V1.0 |
|---|---|
| `scripts/rd_pano_to_splat.py` | موتور CPU (PHASE 1: راستی‌آزمایی قدم‌به‌قدم) |
| `docs/rd-artifacts/survey/cabin_splat.ply` | خروجی PLY مرجع (32.8MB) |
| `public/js/room.js` + `public/vendor/three-0.160.0.module.js` | runtime پروداکشن — **دست‌نخورده در این مأموریت** |
| `docs/12-ai-360-to-3d-rd.md` | کالیبراسیون پوستهٔ doc-12 (مرجع PHASE 7) |
| `docs/14-github-opensource-360-3d-survey.md` | تحقیق متن‌باز کامل (ورودی تصمیم V1.0) |
| `MEMORY_STATE.json` | حافظهٔ پروژه — در پایان مأموریت به‌روز می‌شود |

## 6) مسیر پیش‌رو
PHASE 1 → 9 روی `engine-upgrade-v1`؛ ادغام در `main` فقط پس از regressions سبز؛
صفحهٔ آزمایشی Spark کاملاً ایزوله (`public/labs/engine-v1/`) — **three.js پروداکشن (0.160) در
هیچ مرحله‌ای ارتقا نمی‌یابد** (حکم صریح مالک).
