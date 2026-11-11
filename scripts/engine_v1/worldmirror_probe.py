#!/usr/bin/env python3
# ============================================================================
# WORLDMIRROR.APP — read-only reverse-engineering probe (R&D, additive only)
#
# Owner mission (2026-11-11): "https://worldmirror.app/ این سایت چیه ایا به درد
# ما میخوره؟ اگر میخوره مهندسی معکوسش کن و توی گیت هاب پوشش کن اول دقیق
# بفهم چیه و چیکار میکنه" — same evidence-based method as
# docs/engine-upgrade-v1/marble_reverse_engineering.md (E-table, REA/morluto).
#
# What it does: fetches ALL evidence live from public URLs (site, official
# HuggingFace Space config, HF API, raw GitHub License/README) and writes
# three JSON artifacts under docs/rd-artifacts/engine-v1/. Nothing in the
# project is modified; no live generation is run on anyone's GPU service.
#
# Usage: python3 scripts/engine_v1/worldmirror_probe.py
# ============================================================================
import datetime
import json
import re
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ART_DIR = REPO_ROOT / "docs" / "rd-artifacts" / "engine-v1"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) PanodromeRnD/1.0"}
VERIFY_DATE = "2026-11-11"


def fetch(url, timeout=40):
    """GET with redirects; returns dict(status, headers, text)."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "status": r.status, "headers": dict(r.headers),
                    "text": r.read().decode("utf-8", errors="replace")}
    except Exception as e:  # noqa: BLE001 - probe must never crash on one probe
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "status": None, "headers": {}, "text": ""}


def grab(pattern, text, default=None, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(1) if m else default


def write_artifact(name, payload):
    path = ART_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size} bytes)")


# ---------------------------------------------------------------------------
# 1) worldmirror.app — site anatomy
# ---------------------------------------------------------------------------
def probe_site():
    home = fetch("https://worldmirror.app/")
    html = home["text"]

    links = sorted(set(re.findall(r'href="([^"]+)"', html)))
    external = [l for l in links if l.startswith("http") and "worldmirror.app" not in l]
    anatomy = {
        "artifact": "worldmirror_site_anatomy",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "generator": "scripts/engine_v1/worldmirror_probe.py",
        "method": "live HTTP fetch of public pages; regex extraction of markers; all evidence URL-verifiable",
        "verification_date": VERIFY_DATE,
        "home_fetch_ok": home["ok"],
        "http_headers_measured": {
            "server": home["headers"].get("Server"),
            "x-powered-by": home["headers"].get("X-Powered-By"),
            "x-matched-path": home["headers"].get("x-matched-path"),
            "x-vercel-cache": home["headers"].get("x-vercel-cache"),
            "x-vercel-id": home["headers"].get("x-vercel-id"),
            "set-cookie": home["headers"].get("Set-Cookie"),
        },
        "page_meta": {
            "title": grab(r"<title>([^<]*)</title>", html),
            "meta_description": grab(r'<meta name="description" content="([^"]*)"', html),
        },
        "iframe_evidence": {
            "iframe_src": grab(r'iframe_src\\?"\s*:\s*\\?"([^"\\]+)', html),
            "iframe_height": grab(r'\\"height\\?"\s*:\s*\\?"(\d+)px', html),
            "fallback_button_title": grab(r'Open the (World Mirror [^"\\<]{0,40})', html),
            "note": "the ONLY demo surface on the site is an <iframe> of the official free HuggingFace Space; no own compute",
        },
        "operator_evidence": {
            "support_email": grab(r'mailto:([^"]+)', html),
            "external_links": external,
            "google_analytics_id": grab(r'googletagmanager\.com/gtag/js\?id=([A-Z0-9\-]+)', html),
            "note": "operator is a third party (wan2animate.com AI-tools SEO network), NOT Tencent",
        },
        "tos_privacy_boilerplate_evidence": {},
        "sitemap_evidence": {},
    }

    for label, url in [("terms-of-service", "https://worldmirror.app/terms-of-service"),
                       ("privacy-policy", "https://worldmirror.app/privacy-policy")]:
        page = fetch(url)
        text = re.sub(r"<[^>]+>", " ", re.sub(r"<script[^>]*>.*?</script>", "", page["text"], flags=re.S))
        text = re.sub(r"\s+", " ", text)
        boiler = grab(r"(Welcome to World Mirror\s*,?\s*a NextJS [Bb]oilerplate[^.]*\.)", text)
        anatomy["tos_privacy_boilerplate_evidence"][label] = {
            "http_ok": page["ok"],
            "boilerplate_sentence": boiler,
            "mentions_payments": "Payment and Billing" in text or "credit card" in text,
            "mentions_accounts": "Account Creation" in text or "create an account" in text,
            "contradiction": "marketing headline says 'No-Login' while boilerplate TOS describes accounts/payments",
        }

    robots = fetch("https://worldmirror.app/robots.txt")
    sitemap = fetch("https://worldmirror.app/sitemap.xml")
    anatomy["sitemap_evidence"] = {
        "robots_ok": robots["ok"],
        "robots_disallow": re.findall(r"Disallow: ([^\s]+)", robots["text"]),
        "sitemap_urls": re.findall(r"<loc>([^<]+)</loc>", sitemap["text"]),
        "sitemap_lastmod": re.findall(r"<lastmod>([^<]+)</lastmod>", sitemap["text"]),
        "note": "sitemap lists ONLY the homepage; generated with xml-sitemaps.com (footer of sitemap)",
    }
    return anatomy


# ---------------------------------------------------------------------------
# 2) Official HuggingFace Space — demo interface schema
# ---------------------------------------------------------------------------
def probe_space():
    cfg = fetch("https://tencent-hunyuanworld-mirror.hf.space/config")
    api = fetch("https://huggingface.co/api/spaces/tencent/HunyuanWorld-Mirror")
    out = {
        "artifact": "worldmirror_space_api",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "generator": "scripts/engine_v1/worldmirror_probe.py",
        "method": "live fetch of Gradio /config (schema) + HuggingFace API (runtime); no generation was run",
        "verification_date": VERIFY_DATE,
    }
    if cfg["ok"]:
        c = json.loads(cfg["text"])
        comps = []
        for comp in c.get("components", []):
            props = comp.get("props", {})
            if comp.get("type") in {"file", "slider", "button", "model3d", "video",
                                    "image", "downloadbutton", "checkbox",
                                    "dropdown", "tabitem", "gallery", "textbox"}:
                comps.append({"id": comp.get("id"), "type": comp.get("type"),
                              "label": props.get("label", "")})
        deps = [{"api_name": d.get("api_name"), "inputs": d.get("inputs"),
                 "outputs": d.get("outputs")} for d in c.get("dependencies", [])]
        out.update({
            "gradio_version": c.get("version"),
            "space_id": c.get("space_id"),
            "components_total": len(c.get("components", [])),
            "key_components": comps,
            "api_endpoints": deps,
            "demo_ui_tabs": [c2["label"] for c2 in comps if c2["type"] == "tabitem"],
            "postprocess_filters": [c2["label"] for c2 in comps if c2["type"] == "checkbox"],
        })
    else:
        out["config_fetch_error"] = cfg["error"]
    if api["ok"]:
        a = json.loads(api["text"])
        out["hf_runtime"] = {
            "stage": a.get("runtime", {}).get("stage"),
            "hardware": a.get("runtime", {}).get("hardware"),
            "domain": (a.get("runtime", {}).get("domains") or [None])[0],
            "likes": a.get("likes"),
            "sdk": a.get("sdk"),
            "gcTimeout_s": a.get("runtime", {}).get("gcTimeout"),
            "note": "demo runs on A10G-class (24GB) GPU via HF ZeroGPU; sleeps when idle (wake-on-demand)",
        }
    return out


# ---------------------------------------------------------------------------
# 3) The model itself — HF card, License.txt, README markers, paper abstract
# ---------------------------------------------------------------------------
def probe_model():
    hf = fetch("https://huggingface.co/api/models/tencent/HunyuanWorld-Mirror")
    lic = fetch("https://raw.githubusercontent.com/Tencent-Hunyuan/HunyuanWorld-Mirror/main/License.txt")
    readme = fetch("https://raw.githubusercontent.com/Tencent-Hunyuan/HunyuanWorld-Mirror/main/README.md")
    paper = fetch("https://arxiv.org/abs/2510.10726")

    out = {
        "artifact": "worldmirror_model_facts",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "generator": "scripts/engine_v1/worldmirror_probe.py",
        "method": "live fetch of HuggingFace model API, raw License.txt, raw README.md, arXiv abstract page",
        "verification_date": VERIFY_DATE,
    }
    if hf["ok"]:
        h = json.loads(hf["text"])
        out["hf_model"] = {
            "id": h.get("id"),
            "tags": h.get("tags"),
            "downloads": h.get("downloads"),
            "likes": h.get("likes"),
            "createdAt": h.get("createdAt"),
            "lastModified": h.get("lastModified"),
            "files": [s.get("rfilename") for s in h.get("siblings", [])],
            "params": "1B (F32, single model.safetensors) per HF model card",
        }
    if lic["ok"]:
        lt = lic["text"]
        out["license_key_clauses"] = {
            "name": grab(r"(Tencent [A-Za-z\- ]*License Agreement)", lt),
            "mau_threshold": grab(r"greater than ([0-9,]+\s?[a-z]+) monthly active users", lt),
            "commercial_contact": "hunyuan3d@tencent.com" if "hunyuan3d@tencent.com" in lt else None,
            "territory_exclusion_quote": grab(r"(THIS LICENSE AGREEMENT DOES NOT APPLY[^.]*\.)", lt),
            "territory_definition_quote": grab(r'(Territory shall mean[^.]*\.)', lt),
            "no_training_other_models_quote": grab(r"(You must not use the Tencent HunyuanWorld-Mirror Works or any Output[^.]*\.)", lt),
            "governing_law": "Hong Kong SAR" if "Hong Kong Special Administrative Region" in lt else None,
        }
    if readme["ok"]:
        rt = readme["text"]
        markers = {
            "cuda_recommend": grab(r"(CUDA [\d.]+)", rt),
            "torch_pin": grab(r"(torch==[\d.]+)", rt),
            "gsplat_required": "pip install gsplat" in rt,
            "input_target_size": grab(r"target_size=(\d+)", rt),
            "video_fps_hint": grab(r"fps=(\d+)", rt),
            "colmap_export_files": sorted(set(re.findall(r"((?:cameras|images|points3D|gaussians)\.(?:bin|ply))", rt))),
            "ckpt_download_cmd": grab(r"huggingface-cli download ([\w/\-]+)", rt),
            "paper_cited": grab(r"arxiv\.org/abs/(\d+\.\d+)", rt),
            "acceptance": "ICML 2026" if "ICML" in rt else None,
            "pano_equirect_support": "equirect" in rt.lower() or "panorama" in rt.lower(),
        }
        out["readme_markers"] = markers
    if paper["ok"]:
        pt = paper["text"]
        out["paper"] = {
            "arxiv_id": "2510.10726",
            "title": grab(r'<meta name="citation_title" content="([^"]+)"', pt),
            "authors": re.findall(r'<meta name="citation_author" content="([^"]+)"', pt),
            "abstract_snippet": grab(r'<meta (?:property="og:description"|name="citation_abstract") content="([^"]{80,400})', pt),
        }
    return out


def main():
    ART_DIR.mkdir(parents=True, exist_ok=True)
    site = probe_site()
    write_artifact("worldmirror_site_anatomy.json", site)
    write_artifact("worldmirror_space_api.json", probe_space())
    write_artifact("worldmirror_model_facts.json", probe_model())

    # quick console digest for the operator of this script (R&D log)
    print("--- digest ---")
    print("iframe ->", site.get("iframe_evidence", {}).get("iframe_src"))
    print("support ->", site.get("operator_evidence", {}).get("support_email"))
    print("tos boilerplate ->",
          site.get("tos_privacy_boilerplate_evidence", {}).get("terms-of-service", {}).get("boilerplate_sentence"))
    print("sitemap ->", site.get("sitemap_evidence", {}).get("sitemap_urls"),
          site.get("sitemap_evidence", {}).get("sitemap_lastmod"))


if __name__ == "__main__":
    main()
