# PANODROME — Spatial & Living Architecture Pinterest

> **Repo `mohammadaliaghaabbasi/3d-idea`** · Name locked **2026-11-01** (Issue #1) · `panodrome.com` / `panodrome.io` free at research time — see `docs/11-naming-and-domain.md`.

Transform 360° equirectangular panoramas of real architecture (indoor + outdoor) into
**walkable 6DoF 3D rooms** — connected by AI-detected **Smart Portals**, with **spatial
audio** and an **AI material inspector**. English-first, full RTL Persian from day one.

> **فارسی:** پانودروم — «پینترست فضایی و زنده‌ی معماری». پانوراماهای ۳۶۰ درجه‌ی واقعی به
> اتاق‌های سه‌بعدیِ قابل‌قدم‌زدن تبدیل می‌شوند و با درگاه‌های هوشمند به هم وصل می‌شوند.
> زبان مادر انگلیسی، فارسی راست‌چین کامل از روز اول.

## Which engine? — `walkable-truth/1.0.0` (the only one)

Every 360 page becomes a walkable room through **one** command and **one** engine:

```bash
python3 skills/panodrome_engine.py info      # identity card
python3 skills/panodrome_engine.py list      # which rooms this engine built
python3 skills/panodrome_engine.py build --pano <pano.jpg> --depth <depth.npy> --id <room>
```

The photograph stays on a pristine sphere and is never deformed; a separate **metric**
proxy (exact floor polygon, floor/ceiling heights, obstacle boxes) is what the collider and
the parallax use. Every room carries its fingerprint in `geometry.engine`, so there is
never any doubt which engine produced it. The relief-dome / depth-cut / FOV-zoom stages are
banned. Details, gates and the honest limitations: **[docs/16-engine.md](docs/16-engine.md)**
and **[docs/15-walkable-truth-engine.md](docs/15-walkable-truth-engine.md)**.

## Phase 1 — Core Spatial Engine ✅ (2026-11-01)

The walkable engine is live in `public/` — **10 PolyHaven rooms** (living rooms, lofts,
studios, halls, corridors, cafés, vaulted cellars, cabins, a college quadrangle, an
auditorium) with:

- **6DoF walkable displaced sphere** — panorama + depth map → real room volume with
  true parallax; `WASD` walk, `drag` look, `scroll` glide, safe-zone clamping
- **Smart Portals** — glowing archways placed by an **AI vision door-detection pass**
  (VLM), with 4 routing modes: **Architect / Room Type / Style / Random**
- **Spatial audio engine** — fully procedural WebAudio: footsteps per floor material
  (wood / stone / concrete / carpet / gravel), room-tone ambience, generated
  convolution reverb, portal whoosh + arrival chime
- **Glassmorphism HUD** — EN ⇄ فا RTL toggle, portal mode bar, creator attribution
  (PolyHaven · CC0), AI inspector tooltips on material hotspots

### Run it instantly

```bash
cd public
python3 -m http.server 8000     # or: npx serve public
# open http://localhost:8000
```

Deploy-ready as a **static site** (GitHub Pages / Cloudflare Pages — no build step):

```bash
# publish main + update GitHub Issues (needs token in env T):
T="github_token" bash scripts/publish_phase1.sh

# publish public/ as a GitHub Pages site (same token):
T="github_token" bash scripts/deploy_gh_pages.sh
```

### Re-ingest / extend rooms

```bash
python3 skills/ingest_polyhaven.py            # 10 curated rooms, 4K, procedural depth
python3 skills/ingest_polyhaven.py --only cabin,art_studio
# future: --depth-backend replicate-da2  (Depth Anything 2 / PanDA upgrade hook)
```

## Repo layout

| Path | Role |
|---|---|
| `CLAUDE.md` · `.cursorrules` · `AGENT_BOOT.md` | Agent boot protocol + compact core memory |
| `MEMORY_STATE.json` | Active brain — phase, modules, skills status, next action |
| `skills/ingest_polyhaven.py` | Ingest skill: PolyHaven → panorama + depth + portals + EN/FA metadata |
| `data/rooms_db.json` | Canonical rooms database (10 rooms) |
| `data/vision_overrides.json` | AI vision pass output (facing + door positions per room) |
| `public/` | Panodrome Spatial Engine v1 (static app — deploy root) |
| `docs/` | Research archive: vision, pillars, roadmap, naming, content sources |
| `data/sources.csv` | 80 content sources, license-classified |

## Status

- [x] Ideation & vision (v1)
- [x] Research & seed data — 360 content sources, naming research, language decision (v2)
- [x] **Name locked: Panodrome** · EN-first + FA RTL · direct-to-Phase-1 (2026-11-01)
- [x] **Phase 1 — Core spatial 360→3D walkable engine + first 10 rooms** (this release)
- [ ] Phase 1.5 — DA2/PanDA real depth (replace procedural prior), AI portal detection at scale
- [ ] Phase 2 — automated content pipeline
- [ ] Phase 3 — Pinterest layer (dream home + community upload)
- [ ] Phase 4 — monetization
- [ ] Public launch on Cloudflare (register panodrome.com)

## Update rules

- New ideas/changes land in the matching `docs/` file first, then push.
- Undecided items live in `docs/09-open-questions.md`; once decided → move to the
  owning doc and strike them from the list.
- Agents: read `MEMORY_STATE.json` at turn start, update it at turn end (see `CLAUDE.md`).
