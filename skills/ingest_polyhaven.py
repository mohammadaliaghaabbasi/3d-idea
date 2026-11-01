#!/usr/bin/env python3
"""
Panodrome Ingest Skill #1 — PolyHaven 360° → walkable 3D room ingestion.

Pipeline per room:
  1. Fetch PolyHaven metadata (authors, license, URL) from the public API.
  2. Download the tonemapped equirectangular JPG (highest available) and downscale
     to `--quality` (default 4K, 4096x2048, 2:1 equirect) -> public/assets/panoramas/<id>.jpg
  3. Compute a seamless depth map -> public/assets/depth/<id>_depth.png
       - backend `procedural` (default, offline): analytic box-room ray prior.
         Matches the three.js SphereGeometry convention exactly, so the engine's
         displaced sphere reproduces the room volume with correct 6DoF parallax.
       - backend `replicate-da2` (EXPERIMENTAL, needs REPLICATE_API_TOKEN):
         6x 90-deg perspective faces -> Depth Anything 2 -> equirect reprojection.
         The future DA2/PanDA upgrade path; verify the model slug before use.
     Encoding: two-channel PNG (R = high byte, G = low byte of uint16 little-endian
     value/65535*depth_max) so the browser can decode 16-bit depth from an 8-bit canvas.
  4. Generate a small preview (1024x512) -> public/assets/preview/<id>.jpg
  5. Emit the room record (panorama, depth, portal coordinates ray-cast onto the room
     box, style tags, audio profile, hotspots, bilingual EN/FA metadata, attribution)
     into data/rooms_db.json (canonical) + public/data/rooms_db.json (static deploy copy).

Optional: `--vision-file data/vision_overrides.json`
  {"<room_id>": {"facing": 0.5, "doors": [0.21, 0.74]}}
  Fractions are horizontal positions across the equirect image (0=left edge, 0.5=center).
  `facing` overrides the initial camera view; `doors` (up to 2) place the Smart Portals
  on real doorway positions (AI vision pass) instead of the default side-wall slots.

Usage:
  python3 skills/ingest_polyhaven.py                       # all 10 rooms, 4K, procedural depth
  python3 skills/ingest_polyhaven.py --only art_studio,cabin
  python3 skills/ingest_polyhaven.py --skip-download       # rebuild DB/depth from cached panos
  python3 skills/ingest_polyhaven.py --vision-file data/vision_overrides.json

License note: PolyHaven content is CC0; we credit creators regardless (project pillar).
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.request

try:
    import numpy as np
    from PIL import Image
except ImportError:
    sys.exit("Missing deps: pip install pillow numpy")

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PANO_DIR = os.path.join(REPO_ROOT, "public", "assets", "panoramas")
DEPTH_DIR = os.path.join(REPO_ROOT, "public", "assets", "depth")
PREVIEW_DIR = os.path.join(REPO_ROOT, "public", "assets", "preview")
DATA_DIR = os.path.join(REPO_ROOT, "data")
PUBLIC_DATA_DIR = os.path.join(REPO_ROOT, "public", "data")

API = "https://api.polyhaven.com"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) PanodromeIngest/1.0 (github.com/mohammadaliaghaabbasi/3d-idea)"}

EYE_HEIGHT = 1.6          # meters — panorama camera height assumption
DEPTH_W, DEPTH_H = 2048, 1024
PORTAL_PULLBACK = 0.28    # meters a portal sits in front of its wall
DEFAULT_PORTAL = {"width": 1.15, "height": 2.15}

# Geometric convention (MUST match public/js/panorama.js):
#   pixel (px, py) in a WxH equirect image:
#     phi = 2*pi * px/W ; theta = pi * py/H          (theta 0 = zenith/sky)
#     dir = (-cos(phi)*sin(theta), cos(theta), sin(phi)*sin(theta))
#   Room box: x in [-W/2, W/2], y in [0, H], z in [-D/2, D/2]; camera near center at eye height.

ROOMS = [
    dict(id="anniversary_lounge", type="living_room",
         shape=(4.6, 2.8, 6.0), cam=(0.0, 0.0),
         styles=["classic", "warm", "cozy"], floor="wood",
         audio=dict(ambient="room_tone", reverb=0.25, footsteps="wood"),
         name=dict(en="Anniversary Lounge", fa="نشیمن سالن کلاسیک"),
         desc=dict(en="A warm classic living room with carpet, floor lamps and soft window light.",
                   fa="اتاق نشیمن کلاسیک و گرم با فرش، چراغ ایستاده و نور ملایم پنجره."),
         hotspots=[
             ("oak_parquet", 0.50, -68, "Oak parquet floor", "کف پارکت بلوط",
              "Herringbone oak strips, sanded and oiled.", "تخته‌های بلوط به‌صورت هریینگ‌بون، سمباده و روغن‌کاری‌شده."),
             ("persian_carpet", 0.44, -55, "Hand-woven carpet", "فرش دستباف",
              "Wool pile on a cotton warp, medallion motif.", "پشم گره‌خورده روی چله پنبه‌ای با نقش ترنج."),
             ("brass_lamp", 0.58, 8, "Brass floor lamp", "چراغ ایستاده برنجی",
              "Warm 2700K bulb behind a linen shade.", "لامپ ۲۷۰۰ کلوین پشت حباب کتانی."),
         ]),
    dict(id="photo_studio_loft_hall", type="loft",
         shape=(6.0, 3.4, 9.0), cam=(0.0, 0.0),
         styles=["modern", "minimal", "scandinavian"], floor="wood",
         audio=dict(ambient="city_hum", reverb=0.35, footsteps="wood"),
         name=dict(en="Sunny Loft Hall", fa="سالن لوفت آفتابی"),
         desc=dict(en="A bright modern loft with wooden floors and tall morning windows.",
                   fa="لوفت مدرن و پرنور با کف چوبی و پنجره‌های بلند نور صبح."),
         hotspots=[
             ("light_oak_floor", 0.50, -70, "Light oak flooring", "کف بلوط روشن",
              "Wide-plank engineered oak, matte lacquer.", "تخته‌های پهن بلوط مهندسی با لاک مات."),
             ("plaster_walls", 0.30, 4, "White plaster walls", "دیوار گچی سفید",
              "Lime-plaster finish, soft sheen.", "پوشش گچ آهکی با براقیت ملایم."),
             ("steel_windows", 0.72, 2, "Steel-framed windows", "پنجره‌های فریم فولادی",
              "Slim black steel mullions, double glazing.", "نعلبک‌های فولادی باریک سیاه با شیشه دوجداره."),
         ]),
    dict(id="art_studio", type="studio",
         shape=(5.0, 3.2, 7.0), cam=(0.0, 0.0),
         styles=["artistic", "industrial", "creative"], floor="concrete",
         audio=dict(ambient="room_tone", reverb=0.40, footsteps="concrete"),
         name=dict(en="Painter's Studio", fa="اتودیوی نقاش"),
         desc=dict(en="A creative studio filled with canvases, pigments and daylight.",
                   fa="اتودیویی خلاق پر از بوم، رنگدانه و نور روز."),
         hotspots=[
             ("concrete_floor", 0.50, -72, "Polished concrete", "بتن صیقلی",
              "Power-troweled slab, sealed matte.", "دال بتنی ماله‌زده با درزگیر مات."),
             ("canvases", 0.34, 6, "Stretched canvases", "بوم‌های کشیده‌شده",
              "Linen on spruce stretcher bars.", "کتان روی قاب چوب صنوبر."),
             ("studio_glazing", 0.66, 3, "North-light glazing", "شیشه‌های نور شمالی",
              "Tall factory Crittall-style steel glazing.", "شیشه‌کاری فولادی بلند به سبک صنعتی."),
         ]),
    dict(id="ballroom", type="hall",
         shape=(9.0, 5.5, 14.0), cam=(0.0, 0.0),
         styles=["victorian", "classic", "ornate"], floor="stone",
         audio=dict(ambient="hall_air", reverb=0.70, footsteps="stone"),
         name=dict(en="Victorian Ballroom", fa="تالار بال ویکتوریایی"),
         desc=dict(en="An ornate ballroom with tiled floor, chandeliers and a grand piano.",
                   fa="تالار مجلل با کف کاشی، لوسترهای بلور و پیانوی بزرگ."),
         hotspots=[
             ("encaustic_tiles", 0.50, -70, "Encaustic floor tiles", "کاشی‌های رنگ‌ورورته",
              "Geometric Victorian encaustic tiles.", "کاشی‌های ویکتوریایی هندسی رنگی."),
             ("chandelier", 0.50, 62, "Crystal chandelier", "لوستر بلوری",
              "Cut-glass drops on a brass frame.", "آویزهای بلور بریده روی اسکلت برنجی."),
             ("stucco", 0.28, 10, "Gilded stucco", "گچ‌بری طلایی",
              "Moulded plaster cornices with gold leaf.", "قرنیزهای گچی قالبی با ورق طلا."),
         ]),
    dict(id="large_corridor", type="corridor",
         shape=(3.4, 4.2, 13.0), cam=(0.0, -1.5),
         styles=["victorian", "classic"], floor="stone",
         audio=dict(ambient="hall_air", reverb=0.60, footsteps="stone"),
         name=dict(en="Grand Entrance Corridor", fa="هال ورودی باشکوه"),
         desc=dict(en="A Victorian entrance hall with arched doorways and tiled floor.",
                   fa="هال ورودی ویکتوریایی با طاق‌نماهای قوسی و کف کاشی."),
         hotspots=[
             ("victorian_tiles", 0.50, -72, "Victorian floor tiles", "کاشی کف ویکتوریایی",
              "Chess-pattern encaustic tiling.", "کاشی‌کاری شطرنجی رنگ‌ورورته."),
             ("arch", 0.18, 6, "Arched doorway", "طاق‌نمای ورودی",
              "Brick arch with keystone detail.", "طاق آجری با کلید سنگی."),
             ("paneled_doors", 0.80, 4, "Paneled doors", "درهای پنل‌دار",
              "Four-panel painted timber doors.", "درهای چوبی چهارپنل رنگ‌شده."),
         ]),
    dict(id="comfy_cafe", type="cafe",
         shape=(5.0, 3.0, 7.0), cam=(0.0, 0.0),
         styles=["cozy", "commercial", "rustic"], floor="wood",
         audio=dict(ambient="cafe_murmur", reverb=0.45, footsteps="wood"),
         name=dict(en="Comfy Café", fa="کافه دنج"),
         desc=dict(en="A cozy café corner with couches, warm lamps and low light.",
                   fa="گوشه‌ای دنج از کافه با مبل‌های راحت و نور کم‌سوی چراغ‌ها."),
         hotspots=[
             ("timber_floor", 0.50, -71, "Worn timber floor", "کف چوبی کهنه",
              "Aged pine boards with an oiled patina.", "تخته‌های کهنه کاج با پوشش روغنی."),
             ("brick_wall", 0.30, 6, "Exposed brick wall", "دیوار آجری نمایان",
              "Painted brick, mortar raked back.", "آجر رنگ‌شده با ملات آب‌خورده."),
             ("pendant_lights", 0.55, 58, "Linen pendant lights", "آویزهای کتانی",
              "Warm bulbs in woven linen shades.", "لامپ‌های گرم زیر حباب‌های کتانی بافته."),
         ]),
    dict(id="castle_zavelstein_cellar", type="cellar",
         shape=(3.6, 2.9, 10.0), cam=(0.0, 0.0),
         styles=["gothic", "historic", "stone"], floor="stone",
         audio=dict(ambient="cellar_drip", reverb=0.80, footsteps="stone"),
         name=dict(en="Castle Vaulted Cellar", fa="سرداب قلعه"),
         desc=dict(en="Gothic brick vaults beneath the castle, cool and echoing.",
                   fa="طاق‌های آجری گوتیک زیر قلعه، خنک و طنین‌انداز."),
         hotspots=[
             ("brick_vault", 0.30, 45, "Gothic brick vault", "طاق آجری گوتیک",
              "Pointed arches in bond brickwork.", "طاق‌های تیزه‌ای با آجرچینی بندچین."),
             ("stone_floor", 0.50, -74, "Stone floor slabs", "پلاک‌های کف سنگی",
              "Flags of local sandstone.", "پلاک‌های ماسه‌سنگ محلی."),
             ("arched_niche", 0.74, 2, "Arched niche", "طاقچه قوسی",
              "Storage recess set into the wall.", "جاگاهی در دل دیوار برای انبار."),
         ]),
    dict(id="cabin", type="bedroom",
         shape=(3.5, 2.4, 4.6), cam=(0.0, 0.0),
         styles=["cozy", "rustic", "timber"], floor="wood",
         audio=dict(ambient="room_tone", reverb=0.20, footsteps="wood"),
         name=dict(en="Forest Cabin Room", fa="اتاق کلبه جنگلی"),
         desc=dict(en="An intimate timber cabin bedroom with warm bedside light.",
                   fa="اتاق خواب چوبی و صمیمی کلبه با نور گرم کنار تخت."),
         hotspots=[
             ("pine_walls", 0.30, 6, "Pine plank walls", "دیوار تخته کاج",
              "Tongue-and-groove pine, honey varnish.", "تخته‌های کاج شیار و زبانه با لاک عسلی."),
             ("wool_throw", 0.55, -30, "Wool throw blanket", "پتوی پشمی",
              "Chunky knit lambswool throw.", "پتوی بافت ضخیم از پشم بره."),
             ("reading_sconce", 0.68, 20, "Reading sconce", "آویز مطالعه",
              "Articulated brass wall light.", "چراغ دیوار برنجی مفصلی."),
         ]),
    dict(id="quadrangle_sunny", type="courtyard",
         shape=(24.0, 45.0, 24.0), cam=(0.0, 0.0),   # tall box = open sky; walls = cloister range
         styles=["collegiate", "classical", "open_air"], floor="gravel",
         audio=dict(ambient="birds_wind", reverb=0.05, footsteps="gravel"),
         name=dict(en="Sunny College Quadrangle", fa="حیاط چهارگوش دانشگاه"),
         desc=dict(en="An open collegiate courtyard framed by stone cloisters under the midday sun.",
                   fa="حیاط باز دانشگاه با راهروهای سنگی در آفتاب نیم‌روز."),
         hotspots=[
             ("cloister", 0.50, -2, "Limestone cloister", "راهرو سنگ آهکی",
              "Arcaded walkway with mullioned tracery.", "ایوان طاق‌دار با شبکه‌های سنگی."),
             ("lawn", 0.44, -66, "Courtyard lawn", "چمن حیاط",
              "Close-mown mixed turf.", "چمن متراکم چندگونه."),
             ("mullioned_windows", 0.75, 0, "Mullioned windows", "پنجره‌های شبکه‌دار",
              "Stone-mullioned casements in the range.", "پنجره‌های قاب‌سنگی در بالای راهرو."),
         ]),
    dict(id="school_hall", type="auditorium",
         shape=(9.0, 6.0, 16.0), cam=(0.0, 0.0),
         styles=["institutional", "timber", "hall"], floor="wood",
         audio=dict(ambient="hall_air", reverb=0.60, footsteps="wood"),
         name=dict(en="Old School Hall", fa="سالن مدرسه قدیمی"),
         desc=dict(en="A wooden-floored assembly hall with a stage and tall windows.",
                   fa="سالن اجتماعات با کف چوبی، سکوی نمایش و پنجره‌های بلند."),
         hotspots=[
             ("maple_floor", 0.50, -71, "Varnished maple floor", "کف افرا لاکی",
              "Strip maple on battens, gloss varnish.", "نوارهای افرا روی زیرسازی با لاق براق."),
             ("stage_curtain", 0.50, -4, "Stage curtains", "پرده‌های سکو",
              "Heavy wool serge drapery.", "پرده‌های ضخیم سرژ پشمی."),
             ("timber_trusses", 0.30, 55, "Timber roof trusses", "پاورقی‌های چوبی",
              "Exposed pine trusses with iron ties.", "پاورقی‌های نمای کاج با مهار آهنی."),
         ]),
]

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def http_json(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"    retry {attempt+1}: {e}")
            time.sleep(2 * (attempt + 1))


def download(url, dest, retries=4):
    if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
        print(f"    cached: {os.path.basename(dest)}")
        return
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r, open(dest + ".part", "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(1 << 17)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        print(f"\r    {os.path.basename(dest)} {done*100//total}% ({done/1e6:.0f}/{total/1e6:.0f}MB)", end="")
            os.replace(dest + ".part", dest)
            print(f"\r    downloaded: {os.path.basename(dest)} ({done/1e6:.1f}MB)      ")
            return
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"\n    retry {attempt+1}: {e}")
            time.sleep(2 * (attempt + 1))


def equirect_dir(frac_x, pitch_deg):
    """Direction for horizontal fraction (0..1) and pitch (-90 down .. +90 up), three.js convention."""
    phi = 2.0 * math.pi * frac_x
    theta = math.pi / 2.0 - math.radians(pitch_deg)
    st, ct = math.sin(theta), math.cos(theta)
    return (-math.cos(phi) * st, ct, math.sin(phi) * st)


def box_exit_t(cam, d, shape):
    """Distance from cam (inside the box) to the box surface along unit dir d."""
    W, H, D = shape
    lo = (-W / 2 - cam[0], 0.0 - cam[1], -D / 2 - cam[2])
    hi = (W / 2 - cam[0], H - cam[1], D / 2 - cam[2])
    t = float("inf")
    for i in range(3):
        if d[i] > 1e-9:
            t = min(t, hi[i] / d[i])
        elif d[i] < -1e-9:
            t = min(t, lo[i] / d[i])
    return t


def box_corner_max(cam, shape):
    W, H, D = shape
    return max(math.dist(cam, (x, y, z))
               for x in (-W / 2, W / 2) for y in (0.0, H) for z in (-D / 2, D / 2))


def procedural_depth(shape, cam, out_path):
    """Analytic box-room depth prior as a two-channel uint16 PNG (R=hi, G=lo)."""
    W, H, D = shape
    ys, xs = np.mgrid[0:DEPTH_H, 0:DEPTH_W]
    phi = 2.0 * np.pi * (xs / DEPTH_W)
    theta = np.pi * (ys / DEPTH_H)
    st = np.sin(theta)
    dx = -np.cos(phi) * st
    dy = np.cos(theta)
    dz = np.sin(phi) * st

    cx, cy, cz = cam
    t = np.full((DEPTH_H, DEPTH_W), np.inf)
    for d, hi_b, lo_b in (
        (dx, W / 2 - cx, -W / 2 - cx),
        (dy, H - cy, 0.0 - cy),
        (dz, D / 2 - cz, -D / 2 - cz),
    ):
        with np.errstate(divide="ignore", invalid="ignore"):
            t_pos = np.where(d > 1e-9, hi_b / d, np.inf)
            t_neg = np.where(d < -1e-9, lo_b / d, np.inf)
        t = np.minimum(t, np.minimum(t_pos, t_neg))

    t = _wrap_gaussian(t, sigma=1.5)   # wrap-aware blur -> seamless at the seam

    dmax = box_corner_max((cx, cy, cz), shape) * 1.10
    val = np.clip(t / dmax, 0, 1)
    v16 = (val * 65535).astype(np.uint32)
    img = np.zeros((DEPTH_H, DEPTH_W, 3), np.uint8)
    img[..., 0] = ((v16 >> 8) & 0xFF).astype(np.uint8)
    img[..., 1] = (v16 & 0xFF).astype(np.uint8)
    Image.fromarray(img).save(out_path, optimize=True)
    return dmax


def _wrap_gaussian(arr, sigma):
    """Gaussian blur that wraps horizontally (equirect seam)."""
    radius = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(arr, ((0, 0), (radius, radius)), mode="wrap")
    out = np.zeros(arr.shape, dtype=np.float64)
    for i, w in enumerate(k):
        out += w * pad[:, i:i + arr.shape[1]]
    return out


# ----------------------- EXPERIMENTAL: Replicate DA2 backend ---------------------------

def replicate_da2_depth(pano_path, out_path, model="lucataco/depth-anything-v2"):
    """EXPERIMENTAL DA2 backend: 6 perspective faces -> Depth Anything 2 -> equirect reprojection.

    Requires REPLICATE_API_TOKEN. Untested offline hook for the DA2/PanDA upgrade path;
    verify the Replicate model slug before relying on it.
    """
    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        sys.exit("replicate-da2 backend needs REPLICATE_API_TOKEN in the environment")
    import base64
    import io

    def replicate_run(img_b64):
        body = json.dumps({"input": {"image": f"data:image/png;base64,{img_b64}"}}).encode()
        req = urllib.request.Request(
            f"https://api.replicate.com/v1/models/{model}/predictions",
            data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            pred = json.load(r)
        poll = pred["urls"]["get"]
        while True:
            req = urllib.request.Request(poll, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=60) as r:
                pred = json.load(r)
            if pred["status"] in ("succeeded", "failed", "canceled"):
                break
            time.sleep(2)
        if pred["status"] != "succeeded":
            raise RuntimeError(f"DA2 prediction {pred['status']}")
        out_url = pred["output"] if isinstance(pred["output"], str) else pred["output"][0]
        req = urllib.request.Request(out_url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r:
            return np.array(Image.open(io.BytesIO(r.read())).convert("L"), dtype=np.float64) / 255.0

    img = Image.open(pano_path)
    W_p, H_p = img.size
    depth = np.zeros((H_p, W_p), np.float64)
    weight = np.zeros((H_p, W_p), np.float64)
    faces = [(yaw, 0) for yaw in (0, 90, 180, 270)] + [(0, 90), (0, -90)]
    for yaw, pitch in faces:
        face = _render_perspective(img, yaw, pitch, 90, 768)
        b64 = base64.b64encode(_pil_to_png_bytes(face)).decode()
        d = replicate_run(b64)
        _accumulate_face(depth, weight, d, yaw, pitch, 90, W_p, H_p)
    depth = np.divide(depth, np.maximum(weight, 1e-9))
    np.save(out_path.replace(".png", ".npy"), depth)
    dmax = float(np.percentile(depth, 99.5))
    v16 = (np.clip(depth / max(dmax, 1e-6), 0, 1) * 65535).astype(np.uint32)
    rgb = np.zeros((*v16.shape, 3), np.uint8)
    rgb[..., 0] = ((v16 >> 8) & 0xFF).astype(np.uint8)
    rgb[..., 1] = (v16 & 0xFF).astype(np.uint8)
    Image.fromarray(rgb).save(out_path, optimize=True)
    return dmax


def _pil_to_png_bytes(img):
    import io
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def _render_perspective(img, yaw, pitch, fov, size):
    W_p, H_p = img.size
    arr = np.asarray(img)
    f = 0.5 * size / math.tan(math.radians(fov / 2))
    xs, ys = np.mgrid[0:size, 0:size]
    xd = (xs - size / 2 + 0.5) / f
    yd = -(ys - size / 2 + 0.5) / f
    n = np.sqrt(xd * xd + yd * yd + 1.0)
    x, y, z = xd / n, yd / n, np.ones_like(xd) / n
    cy_, sy_ = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    y2 = y * cy_ - z * sy_
    z2 = y * sy_ + z * cy_
    cyw, syw = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    x3 = x * cyw - z2 * syw
    z3 = x * syw + z2 * cyw
    theta = np.arccos(np.clip(y2, -1, 1))
    phi = np.arctan2(z3, -x3)
    u = (phi / (2 * np.pi)) % 1.0
    px = np.clip((u * W_p).astype(int), 0, W_p - 1)
    py = np.clip((theta / np.pi * H_p).astype(int), 0, H_p - 1)
    return Image.fromarray(arr[py, px])


def _accumulate_face(depth, weight, face_depth, yaw, pitch, fov, W_p, H_p):
    size = face_depth.shape[0]
    f = 0.5 * size / math.tan(math.radians(fov / 2))
    xs, ys = np.mgrid[0:size, 0:size]
    xd = (xs - size / 2 + 0.5) / f
    yd = -(ys - size / 2 + 0.5) / f
    n = np.sqrt(xd * xd + yd * yd + 1.0)
    x, y, z = xd / n, yd / n, np.ones_like(xd) / n
    cy_, sy_ = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    y2 = y * cy_ - z * sy_
    z2 = y * sy_ + z * cy_
    cyw, syw = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    x3 = x * cyw - z2 * syw
    z3 = x * syw + z2 * cyw
    theta = np.arccos(np.clip(y2, -1, 1))
    phi = np.arctan2(z3, -x3)
    u = (phi / (2 * np.pi)) % 1.0
    px = np.clip((u * W_p).astype(int), 0, W_p - 1)
    py = np.clip((theta / np.pi * H_p).astype(int), 0, H_p - 1)
    ang = np.maximum(1e-6, 1.0 / n)   # cos of the off-axis angle
    np.add.at(depth, (py, px), face_depth * ang)
    np.add.at(weight, (py, px), ang)


# --------------------------------------------------------------------------------------
# Main pipeline
# --------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Panodrome PolyHaven room ingester")
    ap.add_argument("--only", help="comma-separated PolyHaven ids")
    ap.add_argument("--quality", default="4k", choices=["2k", "4k"], help="panorama resolution")
    ap.add_argument("--depth-backend", default="procedural", choices=["procedural", "replicate-da2"])
    ap.add_argument("--vision-file", default=None, help="JSON with facing/doors overrides per room")
    ap.add_argument("--skip-download", action="store_true", help="reuse cached panoramas")
    args = ap.parse_args()

    target_w = 4096 if args.quality == "4k" else 2048
    only = set(args.only.split(",")) if args.only else None
    vision = {}
    if args.vision_file and os.path.exists(args.vision_file):
        vision = json.load(open(args.vision_file))
        print(f"vision overrides: {len(vision)} rooms")

    for d in (PANO_DIR, DEPTH_DIR, PREVIEW_DIR, DATA_DIR, PUBLIC_DATA_DIR):
        os.makedirs(d, exist_ok=True)

    print("Fetching PolyHaven asset index ...")
    assets = http_json(f"{API}/assets?type=hdris")
    rooms_out = []

    for cfg in ROOMS:
        rid = cfg["id"]
        if only and rid not in only:
            continue
        print(f"\n=== {rid} ===")
        meta = assets.get(rid) or http_json(f"{API}/assets/{rid}")
        authors = list((meta.get("authors") or {}).keys())
        lic = meta.get("license")
        license_id = lic.get("id", "cc0") if isinstance(lic, dict) else "cc0"

        pano_path = os.path.join(PANO_DIR, f"{rid}.jpg")
        tmp = os.path.join(PANO_DIR, f".{rid}_src.jpg")
        if not args.skip_download:
            files = http_json(f"{API}/files/{rid}")
            tm = files.get("tonemapped") or {}
            if not tm.get("url"):
                print("  !! no tonemapped JPG, skipping")
                continue
            print(f"  source: {tm['url']}")
            download(tm["url"], tmp)

        # downscale to target quality (idempotent)
        need = True
        if os.path.exists(pano_path):
            with Image.open(pano_path) as im:
                need = im.size != (target_w, target_w // 2)
        if need:
            src = tmp if os.path.exists(tmp) else pano_path
            with Image.open(src) as im:
                im.draft("RGB", (target_w, target_w // 2))
                im = im.convert("RGB")
                if im.size != (target_w, target_w // 2):
                    im = im.resize((target_w, target_w // 2), Image.LANCZOS)
                im.save(pano_path, quality=88, optimize=True)
            print(f"  panorama -> {target_w}x{target_w//2} ({os.path.getsize(pano_path)/1e6:.1f}MB)")
        else:
            print(f"  panorama cached at {target_w}")
        if os.path.exists(tmp):
            os.remove(tmp)

        with Image.open(pano_path) as im:
            pw, ph = im.size
            im.resize((1024, 512), Image.LANCZOS).save(
                os.path.join(PREVIEW_DIR, f"{rid}.jpg"), quality=72, optimize=True)

        # depth
        depth_path = os.path.join(DEPTH_DIR, f"{rid}_depth.png")
        shape = cfg["shape"]
        cam = (cfg["cam"][0], EYE_HEIGHT, cfg["cam"][1])
        if args.depth_backend == "replicate-da2":
            dmax = replicate_da2_depth(pano_path, depth_path)
        else:
            dmax = procedural_depth(shape, cam, depth_path)
        print(f"  depth -> {os.path.basename(depth_path)} (max {dmax:.2f}m)")

        # vision overrides
        vis = vision.get(rid, {})
        facing = float(vis.get("facing", 0.5))
        door_fracs = [float(f) for f in vis.get("doors", []) if 0.0 <= float(f) <= 1.0][:2]
        portal_fracs = door_fracs or [0.25, 0.75]
        while len(portal_fracs) < 2:
            portal_fracs.append((portal_fracs[-1] + 0.5) % 1.0)

        # portals ray-cast onto the room box
        portals = []
        for i, f in enumerate(portal_fracs):
            d = equirect_dir(f, 0.0)
            t = box_exit_t(cam, d, shape)
            pos = (cam[0] + d[0] * (t - PORTAL_PULLBACK), 1.07,
                   cam[2] + d[2] * (t - PORTAL_PULLBACK))
            normal = (-d[0], 0.0, -d[2])
            portals.append(dict(
                id=f"{rid}_p{i+1}", fraction=round(f, 4),
                origin="ai_vision_door" if door_fracs else "wall_slot",
                position=[round(pos[0], 3), round(pos[1], 3), round(pos[2], 3)],
                normal=[round(normal[0], 3), round(normal[1], 3), round(normal[2], 3)],
                width=DEFAULT_PORTAL["width"], height=DEFAULT_PORTAL["height"],
                label=dict(en="Smart Portal", fa="درگاه هوشمند"),
            ))

        # hotspots ray-cast
        hotspots = []
        for key, f, pitch, en, fa, note_en, note_fa in cfg["hotspots"]:
            d = equirect_dir(f, pitch)
            t = box_exit_t(cam, d, shape)
            pos = (cam[0] + d[0] * (t - 0.18), cam[1] + d[1] * (t - 0.18), cam[2] + d[2] * (t - 0.18))
            hotspots.append(dict(
                id=f"{rid}_{key}", fraction=round(float(f), 4), pitch=pitch,
                position=[round(pos[0], 3), round(pos[1], 3), round(pos[2], 3)],
                label=dict(en=en, fa=fa), note=dict(en=note_en, fa=note_fa),
            ))

        rooms_out.append(dict(
            id=rid,
            room_type=cfg["type"],
            style_tags=cfg["styles"],
            name=cfg["name"],
            description=cfg["desc"],
            panorama=f"assets/panoramas/{rid}.jpg",
            panorama_size=[pw, ph],
            preview=f"assets/preview/{rid}.jpg",
            depth_map=f"assets/depth/{rid}_depth.png",
            depth_encoding="uint16-two-channel-rgb",
            depth_backend=args.depth_backend,
            depth_max=round(dmax, 3),
            room_shape=dict(width=shape[0], height=shape[1], depth=shape[2]),
            camera=dict(x=round(cam[0], 3), y=EYE_HEIGHT, z=round(cam[2], 3)),
            initial_view=dict(facing=round(facing, 4)),
            portals=portals,
            floor_material=cfg["floor"],
            audio=cfg["audio"],
            hotspots=hotspots,
            hotspots_curated=True,
            attribution=dict(
                creator=", ".join(authors) or "PolyHaven contributor",
                source="PolyHaven", license=license_id.upper(),
                url=f"https://polyhaven.com/a/{rid}",
            ),
        ))

    if not rooms_out:
        sys.exit("no rooms processed")

    db = dict(
        schema="panodrome.rooms_db/1",
        project="Panodrome",
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        content_source=dict(name="PolyHaven", license="CC0", url="https://polyhaven.com"),
        routing_modes=["architect", "room_type", "style", "random"],
        rooms=rooms_out,
    )
    for path in (os.path.join(DATA_DIR, "rooms_db.json"),
                 os.path.join(PUBLIC_DATA_DIR, "rooms_db.json")):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        print(f"wrote {path} ({len(rooms_out)} rooms)")

    print("\nDONE.")


if __name__ == "__main__":
    main()
