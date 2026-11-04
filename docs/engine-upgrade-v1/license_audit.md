# License Audit — PHASE 2
**Mission:** PANODROME — ENGINE UPGRADE V1.0 · **Date:** 2026-11-04 · **Branch:** `engine-upgrade-v1`
**Method:** تأیید مستقل و زنده از GitHub API + HF API (شواهد خام: `docs/rd-artifacts/engine-v1/license_raw/license_audit_raw.json`)

> **حکم نهایی: هر جزئی که در محصول ارسال می‌شود MIT یا Apache-2.0 است — مسیر تجاری V1.0 پاک است.**
> هیچ وزن محدودی وارد محصول نمی‌شود.

---

## ۱) اجزای خط تولید (همگی commercial-safe — تأیید زنده)

| # | جزء | نقش در V1.0 | لایسنس | شاهد زنده (2026-11-04) |
|---|---|---|---|---|
| 1 | **Depth Anything V2 Small** (وزن ONNX، `onnx-community/depth-anything-v2-small` + `depth-anything/Depth-Anything-V2-Small`) | تخمین عمق @CPU | **Apache-2.0** | تگ `license:apache-2.0` در HF API (هر دو مخزن)؛ مخزن رسمی `DepthAnything/Depth-Anything-V2` → **spdx=Apache-2.0** (9,092⭐) ⚠ نکته: ۴۰۴ برای آدرس قدیمی `LiheYoung/Depth-Anything-V2` — مخزن به org منتقل شده |
| 2 | **DA360** (`antigravity-tech/DA360`) | مرجع معماری (ایدهٔ «عمق پانو-native»؛ کدشان کپی نمی‌شود) | **MIT** | spdx=MIT (123⭐، push 2026-10-02) — ادعای مالک تأیید شد |
| 3 | **Niantic SPZ** (`nianticlabs/spz`) | فشرده‌سازی PLY→SPZ (PHASE 3) | **MIT** | spdx=MIT (942⭐، push 2026-11-02) |
| 4 | **Spark** (`sparkjsdev/spark`) | نمایشگر وب (هدف نهایی، three ≥0.180) | **MIT** | spdx=MIT (3,871⭐، push 2026-10-20) |
| 5 | **GaussianSplats3D** (`mkkellogg/GaussianSplats3D`) | نمایشگر جایگزین موقت (three 0.160) | **MIT** | spdx=MIT (2,938⭐) |
| 6 | **three.js** (`mrdoob/three.js`) | موتور WebGL — پروداکشن 0.160 + لاب 0.180 | **MIT** | spdx=MIT (117,536⭐) |
| 7 | **onnxruntime** (`microsoft/onnxruntime`) | CPU inference | **MIT** | spdx=MIT (22,220⭐) |
| 8 | opencv-python / numpy | پیش‌پردازش | Apache-2.0 / BSD-3 | استاندارد |
| 9 | `scripts/rd_pano_to_splat.py` + اسکریپت‌های V1.0 | موتور اختصاصی پانودروم | مالکیت پانودروم | کد خودمان |

## ۲) اجزای محدود (تحقیق/ارزیابی فقط — هرگز در محصول تجاری)

| # | جزء | لایسنس واقعی (تأییدشده) | مبنای شاهد |
|---|---|---|---|
| 10 | **Apple SHARP وزن‌ها** (`sharp_2572gikvuh.pt`) | Apple Model/Research License = **غیرتجاری، فقط پژوهش**؛ کد: Apple Sample Code (spdx=NOASSERTION) | ml-sharp 9,032⭐ + جدول لایسنس README اس‌پی‌اِی‌جی |
| 11 | **PaGeR وزن‌ها** | **CC BY-NC 4.0** (وارثه از DA3 ViT-Giant) | README اس‌پی‌اِی‌جی: «Non-commercial / evaluation» — تأیید حکم مالک |
| 12 | **OmniRoam** (`yuhengliu02/OmniRoam`) | **Adobe Research License = غیرتجاری پژوهشی** (spdx=NOASSERTION، 129⭐، SIGGRAPH 2026) | API + README |
| 13 | **UniSHARP** (`Insta360-Research-Team/UniSHARP`) | **NOASSERTION** — بدون فایل لایسنس = همهٔ حقوق محفوظ | API (353⭐) |
| 14 | Inria 3DGS (reference renderer/optimizer) | غیرتجاری (AceMO/INRIA) — **ما استفاده نمی‌کنیم** (فقط فرمت فایل PLY آن، که یک فرمت داده است) | شناخت عمومی |

## ۳) دو اصلاح نسبت به جدول مالک (صادقانه و مهم)

### ۳.۱) `DECK6/ringsplat` — بله، MIT است؛ ولی خطر باقی می‌ماند
ادعای MIT مالک را **مستقل تأیید کردیم**: spdx=MIT (4⭐، push 2026-04-25). با این حال ringsplat
کیفیتش را از **وزن‌های SHARP اپل** می‌گیرد (پانو → ۶ وجه → SHARP هر وجه) ⇒ خط تولیدش عملاً
با وزن غیرتجاری گره خورده. پس ringsplat برای دموی داخلی/تحقیق آزاد است، برای محصول تجاری نه.
(موتور CPU خودمان را دست نمی‌زندیم — تحت‌تأثیر نیست.)

### ۳.۲) `cedarconnor/SPAG4d` — ادعای MIT در README، اما فایل LICENSE وجود ندارد
README می‌گوید «Core SPAG-4D is **MIT**» و جدولش DA360/DAP را Commercial-OK می‌داند (تأیید شد).
**اما** لیست زندهٔ فایل‌های ریشهٔ مخزن نشان می‌دهد **هیچ فایل LICENSE وجود ندارد** (GitHub API هم
`license=None` برمی‌گرداند). ادعای لایسنس بدون فایل لایسنس از نظر حقوقی مبهم است (پیش‌فرض:
همهٔ حقوق محفوظ) تا زمانی که فایل واقعی commit شود.
**حکم عملی ما:** SPAG4d فقط به‌عنوان **مرجع معماری/مستندات** استفاده می‌شود؛ **هیچ خطی از کدش
کپی نمی‌شود** (خط تولید ما از ابتدا بازنویسی خودمان بوده). ریسک حقوقی برای ما: صفر. برای
صحت‌سنجی خودشان به مالکِ مخزن گزارش شود.

### ۳.۳) نکتهٔ ظریف DAV2
فقط مدل‌های **relative-depth پایه** (کوچک/باز) Apache-2.0 هستند؛ نسخه‌های **metric fine-tuned**
(مدل‌های DPT/DINOv2-based) تحت CC BY-NC منتشر شده‌اند. ما مدل **پایهٔ Small نسبی** را استفاده
می‌کنیم (مطابق PHASE 1) ⇒ Apache-2.0 معتبر است. این تفکیک در ارتقاها باید حفظ شود.

## ۴) ماتریس تصمیم PHASE 2

| تصمیم | وضعیت |
|---|---|
| موتور CPU با DAV2-small ONNX + SPZ + Spark + three.js | ✅ مجاز — همه MIT/Apache-2.0 |
| کپی کد از SPAG4d | ❌ ممنوع (فایل لایسنس ندارد) — فقط مرجع ایده |
| استفاده از SHARP / PaGeR / OmniRoam در محصول تجاری | ❌ ممنوع — وزن غیرتجاری |
| SHARP/ringsplat برای دموی داخلی غیرتجاری/پروتوتایپ | ✅ آزاد (بدون انتشار عمومی) |
| Marble API (تجاری) | خارج از مسیر V1.0 — اختیاری آینده (doc-14 §4) |

**PHASE 2 VERDICT: PASS** — ادامه به PHASE 3 (SPZ).
