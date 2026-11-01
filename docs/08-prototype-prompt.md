# پرامپت آماده‌ی اجرای فاز صفر — نمونه‌ی اولیه‌ی اسکرولی ۳۶۰ درجه

> نسخه v1 — نوامبر ۲۰۲۶ (عیناً از گفتگوی منبع برداشته شده)
>
> این پرامپت برای ساخت سریع یک نمونه‌ی اولیه (Prototype) از تجربه‌ی اسکرولی نوشته شده و آماده‌ی دادن به ایجنت اجرایی است.
>
> **دو نکته پیش از اجرا:**
> 1. تصمیم‌های بازِ `09-open-questions.md` (زبان، اسم، منبع تصاویر) باید پیش از اجرای نهایی اعمال شود.
> 2. بخش اسکرپر (`kuula_scraper.py`) فقط **متادیتا** (عنوان پست، نام و لینک طراح، آدرس embed) استخراج می‌کند — نه فایل خام تصویر؛ رعایت خط قرمز `07-tech-notes.md`.

---

```text
# MISSION: Build an Interactive "Scrollytelling 360° Architectural Tour" Web Platform

You are tasked with building a complete, working prototype of an interactive architectural platform that connects different 360-degree interior/exterior spaces from various designers into one seamless "Dream House" tour controlled via scrolling, complete with designer attribution cards.

Execute the following steps sequentially:

## STEP 1: Project Setup & Structure
Create a clean web project directory named `arch-scroll-tour` containing:
1. `index.html` (Main Scrollytelling 360° Engine using Three.js + GSAP)
2. `kuula_scraper.py` (A Python script using Playwright/BeautifulSoup to fetch Featured Architectural Tours metadata from Kuula.co/explore)
3. `tours_data.json` (JSON database storing the rooms, 360 textures/embed URLs, camera angles, and designer credits)

## STEP 2: Build the Scrollytelling 360° Web Engine (`index.html`)
Write a complete, single-file production-ready HTML/CSS/JS application using **Three.js** and **GSAP (ScrollTrigger)** via CDN with the following exact capabilities:

1. **Dual-Sphere 360° Crossfade Engine:**
   - Create a Three.js scene with a PerspectiveCamera at `(0, 0, 0)` and two concentric `SphereGeometry(500, 60, 40)` meshes (`scale(-1, 1, 1)`) with `transparent: true` materials so we can smoothly cross-fade (`opacity`) between Room A and Room B during scroll transitions.
   - Preload 3 high-resolution equirectangular 360° architectural textures (use reliable, high-res PolyHaven equirectangular JPG URLs for "Modern Entryway", "Luxury Living Room", and "Courtyard Terrace" as default working textures so the app works immediately out of the box).

2. **Scroll-Bound Camera Choreography (GSAP ScrollTrigger):**
   - Create a virtual scroll container (`height: 600vh`).
   - Bind the scroll progress (`0.0` to `1.0`) to the camera's `rotation.y`, `rotation.x`, and `fov`:
     - **0% - 30% (Room 1 - Entryway):** Pan smoothly across the room (`rotation.y` from `0` to `Math.PI * 0.6`).
     - **30% - 35% (Transition 1 -> 2):** Zoom in (`camera.fov` drops from `75` to `35`) towards the doorway while cross-fading Sphere 1 opacity to `0` and Sphere 2 opacity to `1`, then reset `fov` smoothly back to `75`.
     - **35% - 65% (Room 2 - Living Room):** Pan across the second designer's space.
     - **65% - 70% (Transition 2 -> 3):** Zoom transition into the third space.
     - **70% - 100% (Room 3 - Courtyard):** Pan across the third space.

3. **Hybrid Control (Scroll + Free Drag Look-Around):**
   - Allow the user to click/touch and drag on the canvas at any moment to look around freely (add a user offset `dragOffsetLon` and `dragOffsetLat` on top of the GSAP scroll rotation).

4. **Glassmorphism UI & Designer Attribution Card:**
   - Overlay a sleek, modern RTL-supported (Persian/English) Glassmorphism UI card in the bottom-left corner that dynamically updates as the user scrolls from room to room:
     - **Room Title** (e.g., «فضای ۱: لابی ورودی مدرن» / «فضای ۲: نشیمن مینیمال»)
     - **Designer Name & Studio** (Credit to the original creator)
     - **Source Platform Link** (Direct link to designer's Kuula/Portfolio profile)
     - **Progress Bar** showing where the user is inside the combined house tour.

## STEP 3: Build the Kuula Metadata Collector (`kuula_scraper.py`)
Write a Python script using `playwright` (headless) that:
1. Navigates to `https://kuula.co/explore` (or searches architectural tags on Kuula).
2. Extracts the top 5 public architectural posts, capturing:
   - `post_title`
   - `designer_name`
   - `designer_profile_url`
   - `post_url` and `embed_iframe_url` (`https://kuula.co/share/[ID]?logo=1&info=1&fs=1&vr=0&sd=1&thumbs=1`)
   - `thumbnail_url`
3. Saves the output cleanly into `tours_data.json`.

## STEP 4: Verification & Execution
1. Run or verify the HTML file via a local HTTP server (e.g., `python3 -m http.server 8000`) and confirm there are no CORS or WebGL texture errors.
2. Provide me with the final code files or host preview link so I can test the scrolling 360° house tour immediately.
```

---

## خروجی مورد انتظار

- **موتور اسکرولی آماده (`index.html`):** به محض باز شدن، یک خانه‌ی سه‌تکه (ورودی + نشیمن + حیاط) را می‌بینی؛ با اسکرول، دوربین مثل یک فیلم سینمایی در فضا می‌چرخد، به سمت در زوم می‌کند و وارد فضای طراح بعدی می‌شود؛ در هر لحظه با کشیدن موس، ۳۶۰ درجه اطراف قابل گردش است.
- **کارت شناسنامه‌ی طراح (Attribution UI):** یک باکس شیشه‌ای مدرن به زبان فارسی که با عوض شدن هر اتاق، نام طراح آن فضا و لینک پروفایلش را به‌صورت خودکار عوض می‌کند.
- **اسکریپت جمع‌آوری متادیتای پروژه‌های Kuula (`kuula_scraper.py`):** لینک پروژه‌های معماری، نام صاحب اثر و لینک پروفایلشان را استخراج و در `tours_data.json` ذخیره می‌کند.

## تاریخچه تغییرات

- v1 — نوامبر ۲۰۲۶: ثبت اولیه از گفتگوی منبع.
