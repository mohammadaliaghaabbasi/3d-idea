# Security Audit — PHASE 0
**Mission:** PANODROME — ENGINE UPGRADE V1.0 (CPU Splat Engine + Spark Web Runtime)
**Date:** 2026-11-04 · **Branch:** `engine-upgrade-v1` (dev, isolated) · **Base:** `main @ 80aa158`

---

## 1) CRITICAL — GitHub token remains ACTIVE and was previously EXPOSED

| بررسی | نتیجه |
|---|---|
| وضعیت توکن `GITHUB_TOKEN` در `.env` | **ACTIVE** — فراخوانی `GET /user` موفق (HTTP 200، login تأییدشده = mohammadaliaghaabbasi) |
| Scopes | فقط `repo` (کافی برای push؛ بدون دسترسی admin/delete) |
| سابقه افشا | توکن در تاریخچهٔ گفتگوهای قبلی (کانال چت، خارج از مخزن) لو رفته و همان توکن دوباره صادر شده است |

**حکم:** تا وقتی این توکن revoke/regenerate نشود، هر کسی که به آن گفتگوها دسترسی داشته باشد
می‌تواند به مخازن خصوصی مالک push بزند. **این بالاترین ریسک امنیتی پروژه است — بالاتر از
هر ارتقای گرافیکی.**

### اقدام لازم (مالک — دستی، خارج از ساندباکس)
**ایجنت نمی‌تواند PAT را از راه دور باطل کند** — GitHub برای PAT کلاسیک API حذف/ابطال ندارد.
تنها مسیر: `GitHub → Settings → Developer settings → Personal access tokens → Revoke` و ساخت
توکن جدید. سپس مقدار `GITHUB_TOKEN` در `/home/z/my-project/3d-idea/.env` عوض شود (کلید
`GITHUB_TOKEN=` را نگه دارید، فقط مقدار را جایگزین کنید) — **هیچ خط کدی نیاز به تغییر ندارد؛
همهٔ اسکریپت‌ها فقط از `.env` می‌خوانند.**

### قوانین رعایت‌شده در این مأموریت
- توکن هیچ‌جا print/لاگ/screenshot نشد (همهٔ بررسی‌ها با `-w "%{http_code}"` و جداسازی متغیر).
- هیچ توکنی در `git commit`، فایل‌های docs، یا آرتیفکت‌های QA نوشته نشد.

---

## 2) ریشهٔ محرمانگی — وضعیت `.env`

| مورد | وضعیت | اقدام |
|---|---|---|
| مسیر | `/home/z/my-project/3d-idea/.env` (داخل مخزن، ولی ignored) | — |
| `.gitignore` | خط ۵ `.gitignore` شامل `.env` → **verify با `git check-ignore` ✓** | سالم |
| مجوز فایل | **یافتهٔ جدید این ممیزی: 755 (rwxr-xr-x) = قابل‌خواندن توسط group/other** | **اصلاح شد → `-rw-------` (600)** در همین PHASE 0 |
| محتوا | ۴ کلید: `GOOGLE_API_KEY`, `CLOUDFLARE_API_TOKEN`, `GITHUB_TOKEN`, `GEMINI_PROXY_URL` | همان قواعد برای هر ۴ |

---

## 3) اسکن تاریخچهٔ گیت — هیچ توکنی کامیت نشده

`git log --all -p -S 'ghp_'` روی کل تاریخچه اجرا شد: **هیچ رشتهٔ توکنی در هیچ diff یافت نشد**
(تنها مراجعات متنی کامیت 242244d دربارهٔ «tokens hardened in .env» ظاهر شد، بدون خودِ توکن).
`.env` هرگز track نشده و در هیچ کامیتی وجود ندارد.

---

## 4) سایر دیده‌بان‌ها

| مورد | وضعیت |
|---|---|
| اسکریپت‌های deploy (`push_and_deploy.sh`, `deploy_gh_pages.sh`, `cf_deploy_gateway.sh`) | همگی source-only از `.env` — بدون hardcode ✓ |
| Cloudflare token (gateway Worker) | در `.env`، همان توکن قدیمی؛ **توصیه:** هم‌زمان با GitHub token این هم rotate شود |
| `GEMINI_PROXY_URL` | فقط URL داخلی + بدون credential ✓ |
| مخزن آینهٔ `panodrome` | فقط build-output؛ توکن فقط برای push استفاده می‌شود؛ هیچ secret در mirror نیست ✓ |

---

## 5) جمع‌بندی PHASE 0

1. **ریسک بحرانی باز:** توکن GitHub فعال + سابقهٔ افشا → ابطال دستی توسط مالک (تنها راه).
2. **اصلاح‌شده درجا:** مجوز `.env` از 755 → 600.
3. **سالم:** تاریخچهٔ گیت بدون توکن؛ `.env` ignored؛ stash ها دست‌نخورده؛ شاخهٔ dev جدا برای کل مأموریت.
4. توقف لازم نیست — ادامهٔ فازها امن است (ریسک توکن مربوط به گفتگوی قدیمی است، نه کد جدید).
