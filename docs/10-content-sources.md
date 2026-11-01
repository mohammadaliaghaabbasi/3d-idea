# Content Sources — The Complete 360° / Virtual-Tour Source List

> v1 — November 2026 · Research pass: web research + reachability check, data date **2026-11-01**
> Machine-readable version: [`data/sources.csv`](../data/sources.csv)

## خلاصه (فارسی)

- این سند پاسخ به درخواست اصلی مالک پروژه است: «منبع محتوا همه‌جاهایی که ۳۶۰ یا تور می‌ذارن — چون ما همه‌اون رو می‌خایم؛ لیست کامل از منابع.»
- ۶۰+ منبع در ۸ دسته جمع شد؛ برای هر منبع: نوع محتوا، مجوز، روش یکپارچه‌سازی و اولویت خط تولید (P0 = شروع فوری).
- بهترین‌های شروع: **PolyHaven** (CC0، ۱۴۴ پانورامای داخلی + ۹۰۰+ بیرونی)، **ArtStation** (پشتیبانی بومی ۳۶۰ از ۲۰۱۷)، **Kuula** (پلتفرم مرجع)، **Panorra** (جانشین Roundme)، **Matterport Discover**.
- درس تاریخی مهم: **Roundme در ۲۰۲۳ تعطیل شد و همه‌ی تورهای آپلودشده از دست رفت** — استدلال قوی برای استراتژی آرشیو مستقل + رابطه‌ی مستقیم با طراحان (طبق ستون ۵ و `07-tech-notes.md`).
- دسته‌ی «منابع فارسی» یک مزیت راهبردی است: هیچ پلتفرم جهانیِ معماری، محتوای فارسی با کیفیت ندارد — ما از روز اول داریم.

---

## Purpose & how to read

The platform's content strategy (Pillar 5, `02-pillars.md`) needs every place on the internet where 360° panoramas or virtual tours are published. This list is the initial dataset ("دیتای اولیه") for the `HUNTER_CURATOR` agent mode (`05-agent-architecture.md`).

**Integration classes:**

- **INGEST** — open license (CC0/CC-BY or open data). The pipeline may download, process (depth map, portals, audio) and republish **with credit**.
- **EMBED/PERMISSION** — proprietary platform. Use official embed codes or get the creator's explicit permission. Never take raw files (red line in `07-tech-notes.md`).
- **LINK/CREDIT** — editorial or rights-reserved. Link out with full attribution; the creator badge UI (03-ux-ui) handles display.

**Priority:** P0 = first seeding (Phase 2 of roadmap) · P1 = second wave · P2 = later / ecosystem · P3 = regional backlog.

**Status legend (reachability check 2026-11-01):** ✅ HTTP 200 · 🤖 403/4xx (alive, bot-protected) · ⚠️ unreachable from the research sandbox (verify manually; may be geo-blocked) · 💀 dead.

---

## 1. Open-license sources — pipeline can ingest (Class INGEST)

| Source | URL | What it offers | License | Status | Priority |
|---|---|---|---|---|---|
| **PolyHaven** | polyhaven.com | 1,092+ equirectangular HDRIs: **144 interiors** (living rooms, chapels, cafés, museums…), 166 streets/urban, 87 parks, 59 skies, studios… HDR/EXR up to 16K | **CC0** | ✅ | **P0** |
| **Wikimedia Commons** | commons.wikimedia.org | Equirectangular panoramas of real buildings & heritage (search: `equirectangular panorama`) | CC per-file (mostly BY/SA) | ✅ | P1 |
| **Flickr** | flickr.com | CC-licensed 360 photos via API + license filter; active 360 groups | CC per-photo | ✅ | P1 |
| **Sketchfab** | sketchfab.com | Downloadable 3D models (architecture, interiors, museums) with CC0/CC-BY filters — for the 3D/graph layer, not panoramas | CC filters | ✅ | P1 |
| **SketchUp 3D Warehouse** | 3dwarehouse.sketchup.com | Massive library of building/interior models | Mixed per-uploader — check each | ✅ | P2 |
| **BlenderKit** | blenderkit.com | Community assets + HDRIs (freemium) | Mixed | ✅ | P2 |
| **Open Heritage 3D** | openheritage3d.org | Raw heritage scans (CyArk / ICOMOS / partners), real monuments | Open data per-dataset | ✅ | P1 |
| **Smithsonian 3D** | 3d.si.edu | Museum objects & scenes | CC0 | 🤖 | P2 |
| **Scan The World** | myminifactory.com/scantheworld | CC-licensed heritage sculpture scans | CC0 | ✅ | P2 |
| **Zamani Project** | zamaniproject.org | 3D + panoramic documentation of African/heritage sites | Academic — permission | ✅ | P2 |
| 360° in the Wild (research dataset) | paper: Park et al. 2024 | 25,000 real-world panoramas **with depth** | Research use | 📄 | P2 |

## 2. 360° communities & tour platforms (Class EMBED/PERMISSION)

| Source | URL | What it offers | Notes | Status | Priority |
|---|---|---|---|---|---|
| **Kuula** | kuula.co | THE reference platform — archviz 360° community + tour builder (real estate, architecture, art). Our direct "upgrade target" | Embed with credit; scraping raw files is forbidden (red line, `07-tech-notes.md`) | ✅ | **P0** (outreach) |
| **Matterport / Discover** | matterport.com · discover.matterport.com | Largest 3D-tour ecosystem (real estate, hotels, culture); public gallery of millions of spaces | Commercial API/embed | ✅ / 🤖 | P1 |
| **Panorra** | panorra.com | Post-Roundme **social** 360-photo community (closest thing to a "360° Instagram") | Platform ToS | ✅ | **P0** (outreach) |
| **360Cities** | 360cities.net | Curated 360° photo map of the world + **licensing API**; photographers keep rights | Licensing deal needed | ✅ | P1 |
| **AirPano** | airpano.com | High-res aerial 360° of world landmarks & cities (use **.com** — .org unresponsive) | Rights reserved — permission | ✅ | P2 |
| **Gigapan** | gigapan.com | Gigapixel panoramas (cities, heritage) | Per-photo | ✅ | P2 |
| **xRez** | xrez.com | High-end gigapixel cultural/urban panoramas | Permission | ✅ | P2 |
| **Veer.tv** | veer.tv | 360° video community | Platform ToS | ✅ | P2 |
| **Within** | within.co | Cinematic VR/360 experiences | Rights reserved | ✅ | P3 |
| **YouTube 360** | youtube.com | 360° videos incl. archviz walkthroughs | Official embed API | ✅ | P1 |
| **Vimeo** | vimeo.com | 360 support (current policy to verify) | Embed | ✅ | P3 |

**Tour-creation platforms (hosted tours = content pools + competitive map):** GoThru (gothru.co — Street View publishing), Koala360 (koala360.com — built as Roundme replacement), Klapty (klapty.com), SeekBeak (seekbeak.com), CloudPano (cloudpano.com), EyeSpy360 (eyespy360.com), Panoee (panoee.com — free tier), TeliportMe (teliportme.com), ThingLink (thinglink.com), 3DVista (3dvista.com — software + hosting + live guided tours), PanoLite (emerging free tool). All ✅ alive. Priority P2 (ecosystem/competitive).

## 3. Archviz & render communities — the architecture goldmine (Class EMBED/PERMISSION + outreach)

| Source | URL | What it offers | Notes | Status | Priority |
|---|---|---|---|---|---|
| **ArtStation** | artstation.com | **Native 360° equirectangular upload support since 2017** (2:1 images render as interactive panos) + huge archviz community | Per-artist — direct outreach (Pillar 5, phase 2: "the file in exchange for a cinematic showcase + portfolio link") | 🤖 | **P0** (outreach) |
| **CGArchitect** | cgarchitect.com · forums.cgarchitect.com | The professional archviz community & galleries | Community norms | ✅ | P1 |
| **Behance** | behance.net | Archviz projects, often with embedded 360 players | Per-artist | 🤖 | P1 |
| **Evermotion** | evermotion.org | Archviz community & galleries | Per-artist | 🤖 | P2 |
| **Ronen Bekerman** | ronenbekerman.com | Archviz blog & challenges | Permission | 🤖 | P2 |
| **r/ArchViz** | reddit.com/r/ArchViz | Community sharing | Links | 🤖 | P2 |
| Render-engine galleries (Chaos Cosmos, D5 Render, Enscape, Twinmotion, Lumion, Corona) | chaos.com · d5render.com · chaos.com/enscape · unrealengine.com/twinmotion · lumion.com | Engine showcase galleries with 360 output | ⚠️ **Chaos Cosmos is free but EULA-bound (not open)** — renders made with it are fine; do not redistribute assets | 🤖/✅ | P1 (outreach) |

## 4. Architecture media (Class LINK/CREDIT — discovery & credibility)

ArchDaily (✅, VR/virtual-tour articles of real buildings) · Dezeen (✅) · designboom (✅) · Architizer (🤖). Use for editorial curation links, "as covered in" credibility, and finding which real buildings have public tours. Priority P1–P2.

## 5. Heritage & culture (mixed INGEST/LINK)

Google Arts & Culture (✅ — museum/heritage tours incl. architecture) · CyArk (✅, via Open Heritage) · Europeana (🤖, EU aggregator) · Louvre (✅) · British Museum (🤖) · UNESCO WHC (🤖). Priority P1–P2.

## 6. Outdoor street-level imagery (Class EMBED via official APIs)

| Source | URL | Notes | Status | Priority |
|---|---|---|---|---|
| **Google Street View** | via Maps JS API | Unlike Kuula iframes, the **StreetViewPanorama JS object allows programmatic camera control (POV/heading)** — potentially attachable to our portal graph for outdoor spaces. Verify at build time. | alive | P1 (tech spike) |
| Apple Look Around | maps.apple.com | MapKit embeds | ✅ | P2 |
| Yandex Panoramas | yandex.com/maps | Strong RU/CIS + partial world coverage | ✅ | P2 |
| Mapillary | mapillary.com | Crowdsourced street-level; many CC-BY sequences | 🤖 (bot-blocked) | P1 |
| KartaView | kartaview.org | Open dashcam/360 imagery | ✅ | P3 |
| Baidu / Tencent / Kakao-Naver panoramas | — | Regional giants (CN/KR); unverified from sandbox | ⚠️ | P3 |

## 7. Persian-language sources (FA content — strategic differentiator)

| Source | URL | What it offers | Status | Priority |
|---|---|---|---|---|
| **360nama** | 360nama.com | Iranian virtual-tour platform: city tours (Tehran, Shiraz, Isfahan, Tabriz, Mashhad, Kish, Yazd, Kashan, Rasht) + **real-estate 360 tours** | ✅ | P1 (FA seeding / partnership) |
| **Aparat** | aparat.com | Iranian video platform; 360°/VR content exists; verify 360 player support | ⚠️ (504 from sandbox — geo) | P2 |
| Golestan Palace & heritage sites | golestanpalace.ir | Iranian heritage virtual tours | ⚠️ (unreachable from sandbox — verify manually) | P2 |
| Iranian commercial 360 demand | e.g. banktalar.com (wedding-hall 360 tours) | Signal: Iranian businesses already pay for 360 | via search | P3 |

**Strategic note:** Persian-language 360 content is scarce and scattered — and no global architecture platform serves Persian speakers. FA parity from day one (per `01-vision.md` language strategy) turns this gap into a moat: Iranian/Persian architecture (Isfahan, Persepolis, Persian gardens…) is world-class heritage with global demand.

## 8. Dead platforms — the lesson

- **Roundme** — shut down **2023**; *all uploaded tours were lost* (documented by CA State Parks among others). Successors: Panorra (social), GoThru, Koala360.
- **Google Poly** — shut down 2021 (3D models).
- **Google Tour Creator** — discontinued 2021.

**Lesson for us:** content living only inside a third-party platform can vanish overnight. Our value proposition to creators — *your space becomes a walkable, credited, permanent showcase with a portfolio link* — is exactly what Roundme's death proved the market needs.

---

## Recommended pipeline order (ties to `05-agent-architecture.md` + `07-tech-notes.md`)

1. **P0 — engine testing + first rooms:** PolyHaven CC0 (immediate, legal, high-quality, indoor + outdoor).
2. **P0 — creator outreach:** ArtStation + Kuula archviz artists (file in exchange for cinematic showcase + credit + portfolio link — per Pillar 5).
3. **P1 — embeds:** YouTube 360, Matterport, Google Arts & Culture, Street View API (outdoor), Mapillary.
4. **P1–P2 — partnerships & licensing:** 360Cities (API), 360nama (FA), heritage organizations (Zamani, Open Heritage 3D, CyArk).

## To-verify backlog

Vimeo 360 current policy · Sketchfab 360-photo support (vs models only) · Baidu/Tencent/Kakao panorama APIs · more Iranian arch-specific 360 producers · PanoLite maturity · 3DVista hosting terms · Mapillary 360 (vs dashcam) ratio.

## تاریخچه تغییرات

- v1 — نوامبر ۲۰۲۶: پژوهش اولیه — ۶۰+ منبع در ۸ دسته، کلاس‌بندی مجوز/یکپارچه‌سازی، اولویت P0–P3، وضعیت دسترسی ۲۰۲۶-۱۱-۰۱.
