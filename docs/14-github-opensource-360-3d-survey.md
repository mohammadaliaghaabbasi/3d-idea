# ۱۴ — پیمایش جامع متن‌باز گیت‌هاب و HuggingFace: پانوراما ۳۶۰ → ۳D قابل‌قدم‌زدن و Gaussian Splatting (۲۰۲۴–۲۰۲۶)

> مأموریت مالک ۲۰۲۶-۱۱-۰۴: «Emergency Cartoon Purge» + تحقیق عمیق متن‌باز.
> خروجی این سند = مبنای تصمیم «موتور اصلی» پانوراما‌ها برای مرحله بعد پانودروم.

---

## ۰) وضعیت پاکسازی سایت زنده (بخش ۱ مأموریت — انجام‌شده)

**ریشه مشکل کارتونی:** جلسهٔ قبل (MASTER UPGRADE نیمه‌کاره) مدل‌های procedural کم‌ضلع `build_all_3d_rooms.py` را نه‌فقط تولید کرد، بلکه یک بار deploy هم زد — یعنی سایت زنده واقعاً آلوده بود: `rooms_db.json` زنده برای **هر ۱۱ اتاق** فایل GLB رفرنس می‌داد و `assets/true3d/cabin.glb` و امثالش روی دامنه زنده 200 می‌دادند.

**اقدام پاکسازی (non-destructive):**
- کل WIP کارتونی (۱۰ GLB + `dollhouse.js`/`materials.js`/`radar.js` + `build_all_3d_rooms.py` + `true3d_lib.py` + `master_e2e.sh` + DB آلوده) با `git stash push -u` آرشیو شد (بازیافت‌پذیر: `git stash list` → `master-upgrade-WIP cartoon purge 2026-11-04`). درخت کاری = بایت‌به‌بایت کامیت `0eba439` (همان کامیت E2E 69/69).
- **دروازهٔ دود جدید `scripts/purge_smoke.sh`: 14/14 ALL GREEN** روی درخت پاک: بوت صفر خطا، ۱۱ فضا، ویلای true3d (meshes>50، fov قفل 72)، `fetch('/assets/true3d/cabin.glb')` → **404**، اتاق cabin روی SphereGeometry خالص (radius=500، دقیقاً ۱۲۵۱۳ رأس 129×97، bounding radius=500 = صفر جابه‌جایی رأس)، موبایل 390×844 صفر خطا + HUD داخل ۸px.
- **deploy تمیز اجرا شد** و سایت زنده تأیید شد:

| بررسی زنده (post-deploy) | نتیجه |
|---|---|
| `assets/true3d/cabin.glb`, `ballroom.glb`, `anniversary_lounge.glb` | **404 — حذف کامل** |
| `assets/true3d/modern_3d_villa.glb` (دموی معماری true-3d) | 200 ✓ (تنها GLB باقی‌مانده) |
| `data/rooms_db.json` زنده | بایت‌به‌بایت برابر DB پاک (فقط ویلای `glb` دارد) |
| md5 پانورامای cabin زنده | `253ecf743664887cdfe29936f01facb1` = فایل مخزن ✓ |

سایت زنده اکنون: ۱۰ اتاق = عکس ۴K تختِ بدون اعوجاج روی SphereGeometry(500,128,96) + Floor Waypoints + پورتال‌های درگاه (walk-in) + رادار پلان ۲D + ۱ ویلای true-3d. **صفر گلیچ کارتونی.**

---

## ۱) دستهٔ ۱ — مولدهای Feed-Forward پانوراما/تک‌تصویر → 3DGS

### ۱.۱) چرا Pano2Room و DreamScene360 شکست خوردند (درس جلسهٔ قبل)
هر دو per-scene optimization هستند: به CUDA + ~24GB VRAM و ده‌ها دقیقه زمان برای **هر صحنه** نیاز دارند و Space عمومی هم ندارند. در این ساندباکس (2-core Xeon، بدون GPU، ۳.۹GB RAM) غیرقابل اجرا و برای خط تولید اتاق‌به‌اتاق نامناسب.

### ۱.۲) جدول کامل (دادهٔ زندهٔ GitHub API در 2026-11-04 — `docs/rd-artifacts/survey/github_repos.json` + `github_round2.json`)

| مخزن | ⭐ | آخرین push | لایسنس | ورودی | خروجی | نیاز سخت‌افزاری | اجرای بدون GPU؟ | حکم |
|---|---|---|---|---|---|---|---|---|
| [apple-aiml-research/ml-sharp](https://github.com/apple-aiml-research/ml-sharp) (SHARP) | ۹۰۳۲ | 2026-09-11 | کد: Apple Sample Code · **وزن‌ها: Apple Research = غیرتجاری** | ۱ تصویر perspective | 3DGS `.ply` در <۱ ثانیه | prediction روی **CPU/CUDA/MPS**؛ رندر ویدئو فقط CUDA | prediction بله — اما چک‌پوینت fp32 **۲.۸GB** (در RAM ۳.۹GB ما جا نمی‌شود) | کیفیت/سرعت بی‌رقیب؛ **موانع: لایسنس وزن غیرتجاری + حجم** |
| [Insta360-Research-Team/UniSHARP](https://github.com/Insta360-Research-Team/UniSHARP) | ۳۵۳ | 2026-06-11 | NOASSERTION | تک‌تصویر/پانوراما (universal SHARP) | 3DGS | GPU | مستقیم خیر | جانشین تعمیم‌یافتهٔ SHARP از تیم Insta360؛ لایسنس نامشخص |
| [cedarconnor/SPAG4d](https://github.com/cedarconnor/SPAG4d) | ۲۳۲ | 2026-06-12 | **بدون فایل LICENSE = همهٔ حقوق محفوظ** | پانورامای equirect | `.ply`/splat با ۴ بک‌اند: **DA360** (Depth-Anything 360 — Apache-2.0)، DAP، PaGeR، SHARP-360، UniSHARP-360 | GPU 6–12GB VRAM (refinement تا 48GB) | خودِ ابزار خیر؛ اما **ایدهٔ DA360 با DAV2-small ONNX روی CPU بازتولید و تست شد** (بخش ۱.۳) | دقیقاً همان مسئلهٔ ما؛ کد قابل کپی نیست، معماری قابل بازتولید |
| [DECK6/ringsplat](https://github.com/DECK6/ringsplat) | ۴ | 2026-04-25 | **MIT** | پانوراما → cube-face → SHARP هر وجه | `.ply` ادغام‌شده | **Apple Silicon MPS / CUDA / CPU** (`--device cpu`!) | بله (روی Mac سریع؛ روی CPU x86 کند) | سبک‌ترین مسیر legal برای الگوی pano→SHARP؛ کیفیت وابسته به SHARP |
| [chengzhag/PanSplat](https://github.com/chengzhag/PanSplat) (CVPR'25) | ۲۴۲ | 2026-04-19 | **MIT** | **۲ پانوراما** wide-baseline | Spherical Gaussian Pyramid → novel views | 512 سبک؛ 2048 → **24GB VRAM** (RTX 3090) | خیر (feed-forward اما CUDA-محور) | view synthesis بین ۲ پانو؛ برای ما فقط اگر هر اتاق ۲ عکس داشته باشیم |
| [donydchen/MVSplat360](https://github.com/donydchen/MVSplat360) (NeurIPS'24) | ۳۲۷ | 2026-05-06 | **MIT** | ۲+ نمای sparse | پانورامای ۳۶۰ نووِل | CUDA | خیر | خویشاوند MVSplat برای 360؛ Space ندارد |
| [thucz/splatter360](https://github.com/thucz/splatter360) (CVPR'25) | ۱۷۹ | 2025-09-29 | بدون لایسنس مشخص | ۲ پانوراما wide-baseline | 3DGS | CUDA | خیر | generalizable اما دوتایی |
| [zhichu99/PanoSplatt3R](https://github.com/zhichu99/PanoSplatt3R) (ICCV'25) | ۳۵ | 2025-10-17 | بدون لایسنس مشخص | ۲+ پانورامای unposed | 3DGS | آموزش L40 48GB؛ inference سنگین | خیر | جدیدترین پانو-native؛ وزن‌ها روی HF (`zhichu99/PanoSplatt3R`)، Space ندارد |
| [nerficg-project/SPaGS](https://github.com/nerficg-project/SPaGS) | ۷۰ | 2025-07-25 | **MIT** | پانوراما | 3DGS | per-scene **train** | خیر | سریع‌تر از Pano2Room اما باز هم per-scene |
| [LeoDarcy/360GS](https://github.com/LeoDarcy/360GS) | ۱۰۷ | 2025-06-11 | وابسته به 3DGS (غیرتجاری INRIA) | پانوراما + layout | 3DGS برای roaming | per-scene train + CUDA | خیر | layout-guided؛ لایسنس 3DGS غیرتجاری |
| [TrickyGo/Pano2Room](https://github.com/TrickyGo/Pano2Room) (SIGGRAPH'24) | ۱۵۵ | 2024-08-23 | MIT | ۱ پانوراما | mesh/3DGS | CUDA 24GB، ~۳۰ دقیقه/صحنه | **خیر (تست‌شده، شکست)** | مرجع علمی؛ غیرعملی برای ما |
| [ShijieZhou-UCLA/DreamScene360](https://github.com/ShijieZhou-UCLA/DreamScene360) (ECCV'24) | ۱۳۳ | 2026-05-13 | NOASSERTION | متن/پانوراما | صحنه | CUDA سنگین | خیر | همان داستان per-scene |
| [KovenYu/WonderWorld](https://github.com/KovenYu/WonderWorld) | ۷۴۶ | 2025-04-14 | بدون لایسنس مشخص | ۱ تصویر | صحنه تعاملی | GPU | خیر | diffusion-based؛ پرنور و سنگین |
| [3DTopia/LGM](https://github.com/3DTopia/LGM) (ECCV'24 Oral) | ۲۱۲۴ | 2024-08-20 | **MIT** | ۴ نمای multi-view (از ۱ تصویر با diffusion) | 3DGS `.ply` | GPU برای diffusion | **Space زندهٔ ZeroGPU در حال RUN: `ashawkey/LGM`** | مسیر remote رایگان موجود |
| [AiuniAI/Unique3D](https://github.com/AiuniAI/Unique3D) (NeurIPS'24) | ۳۵۹۶ | 2025-07-17 | **MIT** | ۱ تصویر | **mesh** GLB (نه splat) | GPU / **Space ZeroGPU RUN: `Wuvin/Unique3D`** | بله از طریق Space | مکمل per-object |
| [microsoft/TRELLIS.2](https://huggingface.co/spaces/microsoft/TRELLIS.2) | — | فعال | MIT | ۱ تصویر/پانوراما | asset سه‌بعدی (GLB/SLAT) | GPU / **Space ZeroGPU RUN** | بله از طریق Space (سهمیه) | جانشین مدرن TRELLIS؛ API کامل شمارش شد |
| open-mmlab GS-LRM | — | — | — | sparse views | 3DGS | — | — | **مخزن رسمی در دسترس نیست**؛ فقط میرور غیررسمی `InternRobotics/gs-lrm-unofficial` (۷۳⭐ MIT) |
| [imlixinyang/Director3D](https://github.com/imlixinyang/Director3D) | ۳۸۲ | 2025-03-14 | NOASSERTION | متن/دوربین | 3DGS صحنه | GPU سنگین | خیر | video-to-3DGS مولد |
| [3DTopia/LayerPano3D](https://github.com/3DTopia/LayerPano3D) (SIGGRAPH'25) | ۳۲۶ | 2025-07-24 | **Apache-2.0** | **متن** → پانورامای لایه‌ای | صحنه layered | GPU | خیر | مولد (نه بازسازی از عکس ما) اما مدل مفید برای تولید اتاق جدید در آینده |
| [eldar/flash3d](https://github.com/eldar/flash3d) | ۳۳۶ | 2025-06-02 | بدون لایسنس مشخص | ۱ تصویر | 3DGS | GPU | خیر | generalizable تک‌تصویر؛ روی تصویر perspective نه پانوراما |

**نتیجهٔ کلیدی دستهٔ ۱:** هیچ پروژهٔ متن‌باز پانو-native تک‌عکسیِ feed-forward با لایسنس تجاری‌امن و اجرای CPU وجود ندارد؛ نزدیک‌ترین‌ها یا دوتایی‌ورودی‌اند (PanSplat/Splatter-360/PanoSplatt3R)، یا per-scene (SPaGS/360GS/Pano2Room)، یا غیرتجاری (SHARP/UniSHARP).

### ۱.۳) تست زندهٔ مسیر CPU در همین ساندباکس (تولید شده توسط ما — بازتولید معماری DA360)

`scripts/rd_pano_to_splat.py` — مسیر **کاملاً CPU و تجاری‌امن** (Apache-2.0 + MIT):

```
cabin.jpg (4096×2048)
  → DAV2-small ONNX (onnx-community، وزن Apache-2.0) @1022×518 روی CPU: 5.68s
  → وارون‌سازی disparity→depth + کالیبراسیون متری کف (k=7.15، 66430 ردیف کف)
  → unprojection ایکویرکت (همان قرارداد room.js: u=atan2(dz,-dx)): 0.30s
  → خروجی INRIA 3DGS .ply: 132,349 اسپلت، 32.8MB در 0.37s   ← مجموع 6.35s
```

رندرهای CPU دوربین‌جابه‌جا‌شده + حکم VLM (TIER-2):
- نمای مرکز: «اتاق کابین موجه با دیوارهای بژ و سازه‌های چوبی و تخت، خطوط افقی مستقیم، بدون سوراخ سیاه» ✓
- **جابه‌جایی ۱.۳ متر**: «جابه‌جایی پرسپکتیو واقعی، جابه‌جایی عمق درست نزدیک/دور — به‌همراه سوراخ‌ها و کشیدگی در نواحی uncover شده (محدودیت ذاتی تک‌پانوراما)» ✓ — این همان پارالاکس واقعی است که هیچ dome/relief جعلی نمی‌تواند تولید کند.

### ۱.۴) تست‌های زندهٔ مسیر remote رایگان (ZeroGPU Spaces — `scripts/rd_probe_spaces*.py`)

| Space | وضعیت API | نتیجهٔ generation واقعی |
|---|---|---|
| `gagndeep/Apple-Sharp-...` | `/run_sharp` → خروجی **DownloadButton .ply** | AppError بالادستی (کوته) |
| `inoculatemedia/Apple-Sharp-...` | همان | ReadTimeout |
| `Yosun/Apple-Sharp-...` | PAUSED | غیرفعال |
| `microsoft/TRELLIS.2` | API کامل: `/start_session` `/preprocess_image` `/image_to_3d` `/extract_glb` | AppError (احتمالاً سهمیهٔ ZeroGPU ناشناس) |
| `ashawkey/LGM` | RUN | API لیست شد؛ generation تست نشد (ورودی ۴ نمای) |
| `Wuvin/Unique3D` | RUN (ZeroGPU) | بدون تست این بار (سابقهٔ doc-12: مسیر remote per-object با Hunyuan3D-2 اثبات شده) |

**حکم صادقانه:** مسیر remote رایگان «موجود اما ناپایدار» است — وابسته به سهمیهٔ ZeroGPU ناشناس و آینه‌های community. برای تولید offline اتاق‌به‌اتاق قابل اتکا نیست؛ برای per-object گاه‌به‌گاه (مثل Hunyuan3D-2 در doc-12) کار می‌کند. **مسیر CPU محلی پایدارترین گزینهٔ رایگان ماست.**

### ۱.۵) نکتهٔ حیاتی لایسنس SHARP
- کد: Apple Sample Code License (استفاده/توزیع با شرایط اپل).
- **وزن‌ها (`sharp_2572gikvuh.pt`): Apple Machine Learning Research License = «صرفاً Research Purposes غیرتجاری».** اگر پانودروم روزی monetize شود (doc/04)، استفاده از وزن SHARP/UniSHARP در تولید محتوا = ریسک حقوقی. برای نمونه/تحقیق آزاد است.

---

## ۲) دستهٔ ۲ — نمایشگرهای WebGL/WebGPU و فشرده‌ساز `.spz`

| پروژه | ⭐ | push | لایسنس | رندرر | فرمت‌ها | سازگاری three.js | حکم برای ما |
|---|---|---|---|---|---|---|---|
| [sparkjsdev/spark](https://github.com/sparkjsdev/spark) (World Labs) | ۳۸۷۱ | **2026-10-20** | **MIT** | WebGL2 (هدف ۹۸٪+ دستگاه‌ها) | **.ply (خام+فشرده) · .spz · .splat · .ksplat · SOGS** | `@sparkjsdev/spark@2.4.0` → peer **three >=0.180** (نسخه‌های 0.1.x ~9MB با three قدیمی‌تر) | **انتخاب نهایی** — سریع روی موبایل، LOD استریمی، ادغام صحنه با mesh؛ نیازمند ارتقای three از 0.160 به r180+ |
| [mkkellogg/GaussianSplats3D](https://github.com/mkkellogg/GaussianSplats3D) | ۲۹۳۸ | 2025-10-19 | **MIT** | WebGL | .ply/.splat/.ksquat(.ksplat) | `>=0.160.0` — **با three فعلی ما سازگار** | گزینهٔ گذار بی‌درنگ؛ سورت CPU، موبایل ضعیف‌تر، توسعه کند شده |
| [playcanvas/supersplat](https://github.com/playcanvas/supersplat) | ۱۰۵۸۴ | 2026-10-31 | **MIT** | — | ویرایشگر (نه runtime three.js) | — | ابزار ویرایش/برش/فشرده‌سازی عالی برای آماده‌سازی اسپلت‌ها؛ موتور نمایش ما نیست |
| [nianticlabs/spz](https://github.com/nianticlabs/spz) | ۹۴۲ | **2026-11-02** | **MIT** | — | فرمت `.spz` (v2-v4) + بایندینگ C++/JS-WASM/**Python** | — | **تست زندهٔ موفق**: `pip install .` روی همین CPU (بدون GPU) → تبدیل PLY ما: **32.82MB → 1.09MB = ۳۰×** در 0.15s با roundtrip سالم (دلتای موقعیت ≤0.12mm) |
| [antimatter15/splat](https://github.com/antimatter15/splat) | ۳۰۸۴ | 2025-11-16 | MIT | WebGL | .splat | مستقل | مرجع کلاسیک |
| **three.js r186 native** ([discourse](https://discourse.threejs.org/t/native-gaussian-splatting-in-three-js-for-webgpu-renderer/93509), [radiancefields](https://radiancefields.com/three.js-merges-a-native-gaussian-splat-renderer-for-webgpu-in-r186)) | — | r186 | MIT | **WebGPURenderer + fallback جاوااسکریپتِ WebGL** | SPZLoader · SPLATLoader · KSPLATLoader · PLYLoader helper · **glTF KHR_gaussian_splatting** | نیازمند three ≥r186 | آیندهٔ بومی؛ اما WebGPU روی Safari 26/iOS 26 «پیش‌فرض ولی پرگوشه» (گزارش‌های device-lost) — برای iPhone 13 امروز ریسکی |

### حکم موبایل Safari (iPhone 13)
- امروز: **Spark روی WebGL2** = امن‌ترین مسیر (Safari 15.4+ همه WebGL2 دارند).
- Safari 26/iOS 26 WebGPU را پیش‌فرض روشن کرد اما گزارش‌های ناپایداری (device lost) در جامعه ثبت شده؛ native SPZLoader سه‌جی‌اس (WebGPU-first) را به‌عنوان مسیر آینده نگه می‌داریم، نه مسیر امروز.

### الگوی ترکیبی پیشنهادی «اسپلت مرکزی + کراس‌فید به کرهٔ ۴K»
دقیقاً همان الگویی که مالک پرسید — `SplatMesh` در Spark عضو صحنهٔ three.js است، `renderOrder` و انیمیشن opacity دارد؛ یعنی:
1. کرهٔ ایکویرکت ۴K (LAW 1 — دست‌نخورده، بدون هیچ جابه‌جایی رأس)؛
2. اسپلت `.spz` فقط در هستهٔ r<1.2m دور نقطهٔ عکاسی، با opacity انیمیت‌شده (کراس‌فید ۳۵۰ms) هنگام ورود به حالت قدم‌زدن؛
3. pano پیکسل‌هایش هرگز دست نمی‌خورد — اسپلت یک لایهٔ real-3D جدا است (همان LAW 2 پانودروم: عمق فقط از overlayهای سه‌بعدی واقعی).

---

## ۳) دستهٔ ۳ — تخمین‌گرهای Layout/پلان از پانوراما ۳۶۰

| پروژه | ⭐ | push | لایسنس | خروجی | حکم |
|---|---|---|---|---|---|
| [sunset1995/HorizonNet](https://github.com/sunset1995/HorizonNet) (CVPR'19) | ۳۷۲ | 2026-06-07 | **MIT** | ceiling/wall/floor خطوط افق | پایهٔ کلاسیک؛ فعال‌مانده |
| [fuenwang/LED2-Net](https://github.com/fuenwang/LED2-Net) (CVPR'21 Oral) | ۱۱۵ | 2024-02-03 | **MIT** | layout سه‌بعدی | دقیق‌تر از HorizonNet؛ کندتوسعه |
| [crs4/AtlantaNet](https://github.com/crs4/AtlantaNet) (ECCV'20) | ۸۴ | 2025-02-18 | **MIT** | layout Atlanta (دیوارهای غیرمنظم) | برای فضاهای غیرجعبه‌ای |
| [sunset1995/HoHoNet](https://github.com/sunset1995/HoHoNet) (CVPR'21) | ۱۳۰ | 2023-02-05 | **MIT** | holistic: layout + depth + semantics با latent افقی | بهترین «یک‌مدل-همه‌چیز» قدیمی |
| [zhijieshen-bjtu/DOPNet](https://github.com/zhijieshen-bjtu/DOPNet) (CVPR'23) | ۵۷ | 2025-04-15 | **MIT** | layout با جداکردن صفحات متعامد | + نسخهٔ MV-DOPNet (TPAMI'24، ۱۰⭐) |
| [LIAGM/Bi_Layout](https://github.com/LIAGM/Bi_Layout) (CVPR'24) | ۱۷ | 2024-10-09 | **Apache-2.0** | layout دوجهته — رفع ابهام ۳۶۰ | **جدیدترین پانو-native با لایسنس تمیز** |
| [Starrah/DMH-Net](https://github.com/Starrah/DMH-Net) | ۵۵ | 2023-07-06 | MIT | layout از cubemap | مکمل |

**واقعیت تلخ:** هیچ‌کدام ONNX آماده یا ادعای CPU ندارند — همه PyTorch سی‌دی‌یو-محور دورهٔ خود؛ اجرای inference روی CPU شدنی ولی این‌بار تست نشد. **مسیر عملیِ اثبات‌شدهٔ خودمان (doc-12):** DAV2-small ONNX + کالیبراسیون پوستهٔ اندازه‌گیری‌شده (scale=5.7، cam_h=1.10m برای anniversary) + جداسازی مبلمان → همین الان اتوماتیک و CPU است. پیشنهاد: Bi_Layout را فقط اگر دقت دیوارهای خمیده/اتاق‌های غیرمستطیل به کریتیکال‌ترین اولویت تبدیل شود.

---

## ۴) دستهٔ ۴ — مرجع تجاری: World Labs Marble API

منبع: `docs.worldlabs.ai/llms.txt` + `/api/pricing.md` + `/api/faq` (بازیابی 2026-11-04):

- **ورودی‌ها:** prompt / image / **panorama** / multi-view / video → world پایدار.
- **خروجی‌ها:** **SPZ splat** + **collider mesh** + **scale metadata** (`semantics_metadata`) + depth + GLB mesh export + پانورامای RGB (تولید پانو از تصویر/پانو = ۰ کردیت!).
- **مدل‌ها:** `marble-1.0`، `marble-1.1`، `marble-1.1-plus`، `marble-1.0-draft`.
- **قیمت:** ۱ دلار = ۱۲۵۰ کردیت (حداقل خرید ۶۲۵۰ کردیت = $۵، بی‌انقضا):
  - تولید world کامل: **۱۵۰۰ کردیت = $۱.۲۰ به‌ازای هر پانوراما** (marble-1.0/1.1)
  - draft: ۱۵۰ کردیت = $۰.۱۲
  - marble-1.1-plus: ۱۵۰۰ + تا ۱۵۰۰ متغیر (تا $۲.۴۰)
  - خروجی HQ mesh: ۳۵۰۰ کردیت = $۲.۸۰؛ **خروجی PLY splat: رایگان**
  - ۱۰ اتاق ما = ~$۱۲ یک‌بار مصرف (بدون HQ mesh).
- **نکات:** licensing جهات تولیدشده در FAQ ذکر نشده (باید در ToS پلتفرم بررسی شود — ریسک وابستگی به vendor)؛ rate-limit با HTTP 429؛ اعتبار پیش‌خرید.

---

## ۵) مقایسهٔ نهایی و پیشنهاد موتور اصلی

| معیار | Marble API (تجاری) | SHARP/UniSHARP/ringsplat | SPAG4d (ایده، نه کد) | **موتور CPU خودمان (DAV2+spz)** |
|---|---|---|---|---|
| کیفیت walkable | عالی (world پایدار + collider + scale) | عالی (feed-forward پژوهشی) | خوب (خوب با refinement) | متوسط — پارالاکس واقعی + سوراخ‌های uncover |
| هزینه ۱۰ اتاق | ~$۱۲ (+قیمت‌گذاری آیندهٔ API) | $۰ | $۰ (GPU لازم) | **$۰** |
| سخت‌افزار | هیچ (cloud) | GPU/Mac/RAM بالا | GPU 6–12GB | **CPU 2-core همین ساندباکس — اثبات‌شده** |
| لایسنس/حقوق | ToS بسته، vendor-lock | **وزن‌ها غیرتجاری** (Apple Research) | کد بدون لایسنس (غیرقابل کپی) | **Apache-2.0 + MIT کاملاً تجاری‌امن** |
| سرعت/اتاق | دقیقه‌ها (صف + polling) | <۱s (پس از بارگذاری) | دقیقه‌ها | **~۶.۵ ثانیه** |
| کنترل/ادغام پانودروم | خروجی آماده، بدون کنترل نویز | PLY استاندارد | PLY استاندارد | کنترل کامل: calibration پوستهٔ doc-12 + colliderهای موجود + GLB مبلمان موجود |
| ریسک اصلی | قیمت/وابستگی/ToS | لایسنس + ۲.۸GB وزن | بازنویسی کامل | کیفیت سوراخ‌های disocclusion (راه‌حل: per-object از TRELLIS.2/Hunyuan3D + inpaint دیوار) |

### ✅ پیشنهاد نهایی (توصیهٔ مهندسی صریح)
**موتور اصلی = «Panodrome CPU Splat Engine» (مسیر بازتولیدشده و تست‌شدهٔ DA360):**

```
pano_4k.jpg
 → DAV2-small ONNX @CPU (Apache-2.0، ~۵.۷s)
 → کالیبراسیون متری «پوستهٔ اندازه‌گیری‌شده» doc-12 (کف/سقف/دیوار — دقت بهتر از floor-fit ساده)
 → unprojection ایکویرکت + اسپلت‌های 3DGS (رنگ پیکسل، مقیاس مورب)
 → (اختیاری، بهبود کیفیت) per-object: TRELLIS.2 یا Hunyuan3D-2 از راه دور برای مبلمان حجم‌دار + inpaint دیوار پشت آن
 → فشرده‌سازی nianticlabs/spz (MIT، CPU، ۳۰×) → asset ≤۱.۵MB به‌ازای هر اتاق
 → نمایشگر: Spark (MIT، WebGL2، .spz بومی) روی three r180+ با کراس‌فید آلفا به کرهٔ ۴K موجود
```

دلایل: تنها مسیری که هم **امروز روی زیرساخت ما کار می‌کند** (اثبات زنده)، هم **تجاری‌امن** است، هم با LAWهای صفر-اعوجاج (پیکسل‌های پانو دست‌نخورده) سازگار است، و هم هر سه جزءش MIT/Apache و قابل تعویض قطعه‌به‌قطعه‌اند. SHARP را به‌عنوان **ارتقای اختیاری غیرتجاری** (پروتوتایپ/دمو داخلی) و Marble را به‌عنوان **معیار کیفیت + گزینهٔ پرسرعت در صورت بودجهٔ تجاری** نگه می‌داریم؛ هر وقت Apple لایسنس وزن را بازکرد یا پروژه‌ای مثل UniSHARP با لایسنس تمیز منتشر شد، بک‌اند prediction همین موتور عوض می‌شود و بقیهٔ خط تولید دست‌نخورده می‌ماند.

**تصمیم نمایشگر:** Spark هدف نهایی است ولی three ما 0.160 است → دو گام: (۱) ارتقای vendored three به r180+/r186 و بازاجرای E2E؛ (۲) تا آن زمان اگر خروجی زنده لازم شد GaussianSplats3D با همان three 0.160 کار می‌کند. اسپلت مرکزی r<1.2m + کراس‌فید ۳۵۰ms به کرهٔ ۴K با `renderOrder`/opacity در Spark قابل پیاده‌سازی مستقیم است.

---

## ۶) آرتیفکت‌ها و اسکریپت‌های این پیمایش

| مسیر | توضیح |
|---|---|
| `scripts/rd_survey_github.py` / `rd_survey_github2.py` | پیمایش GitHub API (۳ دسته + جستجوهای ۲۰۲۴–۲۰۲۶) → `docs/rd-artifacts/survey/github_repos.json` + `github_round2.json` |
| `scripts/rd_survey_hf.py` | پیمایش HF Spaces/Models + وضعیت runtime → `hf_spaces.json` |
| `scripts/rd_pano_to_splat.py` | **موتور CPU تست‌شده**: pano→DAV2→3DGS PLY (cabin: 6.35s، 132k اسپلت) |
| `scripts/rd_probe_spaces.py` / `2` / `3` | پروب‌های gradio_client ZeroGPU → `space_probes*.json` |
| `docs/rd-artifacts/survey/cabin_splat.ply` + `cabin_center.jpg` + `cabin_offset_1p3m.jpg` | خروجی موتور + رندرهای پارالاکس (حکم VLM ثبت‌شده) |
| `docs/rd-artifacts/survey/cpu_splat_test.json` | آمار زمان/حجم/کالیبراسیون موتور CPU |
| `scripts/purge_smoke.sh` | دروازهٔ ۱۴ بررسیی پاکسازی (cartoon 404 + SphereGeometry خالص + صفر خطا) — ALL GREEN |
| spz python | `pip install` از `nianticlabs/spz` موفق (v1.1.0)؛ تست فشرده‌سازی ۳۰× |

**یادداشت امنیتی:** توکن GitHub فعلی قبلاً در گفتگو لو رفته و دوباره همان توکن ارسال شده است — برای سلامت مخزن خصوصی، هر زمان `regenerate` کنید؛ اسکریپت‌ها همیشه از `.env` (chmod 600، git-ignored) می‌خوانند.
