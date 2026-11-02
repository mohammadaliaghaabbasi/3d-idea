#!/usr/bin/env python3
"""
Panodrome Smart Model Router — skills/ai_router.py
=================================================
ONE unified entry point for every AI call in this repo. Enforces the
4-Tier Model Selection Law (locked in CLAUDE.md / .cursorrules /
MEMORY_STATE.json) with disk caching for ZERO wasted tokens.

THE 4-TIER LAW
--------------
  TIER 0  Disk cache (`.cache/ai_responses/`)   — repeated prompt+image
          SHA-256 → instant replay, 0 tokens. Checked BEFORE any API.
  TIER 1  Heavy Spatial Architect — 3D room-layout math, precise 2D/3D
          furniture bounding boxes & segmentation masks, complex WebGL
          shader design → gemini-2.5-pro, fallback gemini-2.5-flash
          → z-ai chat. (Pro quota reserved for geometry ONLY.)
  TIER 2  Persian Architecture & Vision QA — fluent Iranian-architect
          Persian copy, material hotspot analysis, doorway crop
          verification → gemini-2.5-flash, fallback z-ai vision.
  TIER 3  Bulk / smoke tests — simple JSON checks, E2E screenshot
          sanity, routine tasks → gemini-2.5-flash-lite (fallback
          gemini-2.0-flash) → z-ai chat.

FALLBACK TRIGGERS (auto, per law): HTTP 429 / 403 quota, 400
FAILED_PRECONDITION (geo-block), 401, network timeout, 5xx after one
retry → walk down the chain, ending at the local `z-ai` CLI.
Geo-block (FAILED_PRECONDITION "User location") disables the Google
backends for the rest of the process — no pointless retries.

SECURITY: the Google AI Studio key lives ONLY in `.env` (git-ignored)
or the GOOGLE_API_KEY env var. It is NEVER written to any tracked
file, log line, or cache entry.

USAGE
-----
  CLI:  python3 skills/ai_router.py --probe
        python3 skills/ai_router.py --tier 1 -p "compute room box..." --json
        python3 skills/ai_router.py --tier 2 -p "توضیح معماری..." -i crop.jpg
        python3 skills/ai_router.py --tier 3 -p "is this JSON valid? {...}" 
        python3 skills/ai_router.py --cache-stats
        flags: --no-cache --refresh --system "..." --json-out --temperature --max-tokens
  API:  from skills.ai_router import Router
        r = Router()
        out = r.generate(prompt=..., images=[...], tier=1, json_mode=True)
        out["text"], out["backend"], out["model"], out["cache_hit"], out["fallback_trace"]

Exit codes: 0 ok (any backend or cache) · 2 all backends failed · 3 bad CLI.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

# --------------------------------------------------------------------------- #
# Constants / tier registry
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = REPO_ROOT / ".cache" / "ai_responses"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
CACHE_SCHEMA = "panodrome.ai_router.cache.v1"
# Current ladder, MEASURED 2026-11-02: the 2.5/2.0 family returns 404
# "no longer available to new users" and points at these 3.x successors:
#   gemini-2.5-pro       -> gemini-3.1-pro-preview
#   gemini-2.5-flash     -> gemini-3.8-flash
#   gemini-2.5-flash-lite-> gemini-3.5-flash-lite
#   gemini-2.0-flash     -> gemini-3.8-flash
PROBE_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-pro",  # legacy: expected 404 deprecation evidence
]


@dataclass
class TierSpec:
    number: int
    name: str
    desc: str
    models: list  # ordered Google chain; z-ai always last
    zai_chat_or_vision: str  # "chat" | "vision" (vision auto-downgrades to chat when no image)
    thinking_budget: Optional[int]  # None = model default; >=1 = explicit budget
    timeout_s: int
    zai_timeout_s: int = 240


TIERS: dict[int, TierSpec] = {
    # Tier→role mapping is the OWNER'S LAW (CLAUDE.md); model names are the
    # measured-current Gemini 3.x successors of the original 2.5 picks.
    1: TierSpec(
        number=1,
        name="heavy_spatial_architect",
        desc="3D room-layout math, precise 2D/3D furniture bounding boxes & "
        "segmentation masks, complex WebGL shader design",
        models=["gemini-3.1-pro-preview", "gemini-3.8-flash"],  # was 2.5-pro -> 2.5-flash
        zai_chat_or_vision="chat",
        thinking_budget=None,  # Pro thinking ON — spatial math needs it
        timeout_s=180,
    ),
    2: TierSpec(
        number=2,
        name="persian_arch_vision_qa",
        desc="Fluent Iranian-architectural Persian copywriting, material "
        "hotspot analysis, doorway crop verification",
        models=["gemini-3.8-flash"],  # was 2.5-flash
        zai_chat_or_vision="vision",
        thinking_budget=None,  # NB: flash-lite 400-rejects explicit thinkingBudget=0
        timeout_s=120,
    ),
    3: TierSpec(
        number=3,
        name="bulk_smoke",
        desc="Simple JSON checks, automated E2E screenshot sanity checks, "
        "routine tasks",
        models=["gemini-3.5-flash-lite", "gemini-flash-latest"],  # was 2.5-flash-lite / 2.0-flash
        zai_chat_or_vision="chat",
        thinking_budget=None,
        timeout_s=60,
    ),
}


# --------------------------------------------------------------------------- #
# Key handling — .env / env var only, NEVER hardcoded, NEVER logged
# --------------------------------------------------------------------------- #
def load_google_key() -> tuple[Optional[str], str]:
    """Return (key, source). Source is 'env' | '.env' | 'none'."""
    key = os.environ.get("GOOGLE_API_KEY")
    if key:
        return key.strip(), "env"
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("GOOGLE_API_KEY") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val, ".env"
    return None, "none"


def _mask(key: Optional[str]) -> str:
    """Near-zero disclosure: generic 'AQ.' prefix + length only (artifacts get committed)."""
    if not key:
        return "<absent>"
    return key[:3] + f"…({len(key)}ch)"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_image_b64(path: Path) -> tuple[str, str]:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    if mime == "image/jpg":
        mime = "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return data, mime


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Gemini REST backend
# --------------------------------------------------------------------------- #
class GeminiError(Exception):
    def __init__(self, reason: str, http_code: Optional[int] = None, retryable: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.http_code = http_code
        self.retryable = retryable


GEO_BLOCK_MARKERS = ("user location is not supported", "location is not supported")


def _gemini_call(
    model: str,
    key: str,
    prompt: str,
    images: Optional[list],
    system: Optional[str],
    json_mode: bool,
    temperature: Optional[float],
    max_tokens: Optional[int],
    thinking_budget: Optional[int],
    timeout_s: int,
) -> dict:
    """POST generateContent. Raises GeminiError on any failure."""
    if requests is None:
        raise GeminiError("requests lib unavailable", retryable=False)
    url = f"{GEMINI_BASE}/models/{model}:generateContent"
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    parts: list[dict] = [{"text": prompt}]
    for img in images or []:
        b64, mime = _read_image_b64(Path(img))
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})
    body: dict[str, Any] = {"contents": [{"role": "user", "parts": parts}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    gen_cfg: dict[str, Any] = {}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"
    if temperature is not None:
        gen_cfg["temperature"] = temperature
    if max_tokens:
        gen_cfg["maxOutputTokens"] = int(max_tokens)
    # Cross-model safety (measured 2026-11-02): gemini-3.5-flash-lite rejects
    # an explicit thinkingBudget of 0 with 400 INVALID_ARGUMENT. Only send the
    # knob when the caller explicitly asks for >=1 budget.
    if thinking_budget is not None and thinking_budget >= 1:
        gen_cfg["thinkingConfig"] = {"thinkingBudget": int(thinking_budget)}
    if gen_cfg:
        body["generationConfig"] = gen_cfg
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout_s)
    except requests.RequestException as exc:
        raise GeminiError(f"network: {type(exc).__name__}", retryable=True) from exc

    if resp.status_code != 200:
        reason = f"http_{resp.status_code}"
        try:
            err = resp.json().get("error", {})
            reason = f"http_{resp.status_code}:{err.get('status', '')}:{err.get('message', '')[:160]}"
        except Exception:
            pass
        low = reason.lower()
        geo = any(m in low for m in GEO_BLOCK_MARKERS)
        retryable = resp.status_code in (500, 503, 504)
        raise GeminiError(reason, http_code=resp.status_code, retryable=retryable) if not geo \
            else GeminiError(reason, http_code=resp.status_code, retryable=False)

    data = resp.json()
    try:
        text = "".join(
            p.get("text", "")
            for p in data["candidates"][0]["content"]["parts"]
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiError(f"unparseable response: {json.dumps(data)[:200]}", retryable=False) from exc
    usage = data.get("usageMetadata") or None
    return {"text": text, "usage": usage, "model": data.get("modelVersion", model)}


# --------------------------------------------------------------------------- #
# z-ai CLI backend (always-available floor of every chain)
# --------------------------------------------------------------------------- #
def _zai_call(
    prompt: str,
    images: Optional[list],
    system: Optional[str],
    vision_mode: bool,
    timeout_s: int,
) -> dict:
    use_vision = vision_mode and bool(images)
    if use_vision and system:
        prompt = f"{system}\n\n---\n\n{prompt}"  # vision CLI has no -s flag
        system = None
    cmd = ["z-ai", "vision" if use_vision else "chat", "-p", prompt]
    if system:
        cmd += ["-s", system]
    for img in images or []:
        cmd += ["-i", str(img)]
    with tempfile.TemporaryDirectory(prefix="ai_router_zai_") as td:
        out_path = Path(td) / "out.json"
        cmd += ["-o", str(out_path)]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_s, cwd=str(REPO_ROOT)
            )
        except subprocess.TimeoutExpired:
            raise GeminiError(f"z-ai timeout after {timeout_s}s", retryable=False)
        if proc.returncode != 0 or not out_path.is_file():
            raise GeminiError(
                f"z-ai exit {proc.returncode}: {(proc.stderr or proc.stdout or '')[:200]}",
                retryable=False,
            )
        try:
            data = json.loads(out_path.read_text())
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage")
            model = data.get("model", "z-ai")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise GeminiError("z-ai unparseable JSON output", retryable=False) from exc
        return {"text": content, "usage": usage, "model": model}


# --------------------------------------------------------------------------- #
# TIER 0 — disk cache
# --------------------------------------------------------------------------- #
class DiskCache:
    def __init__(self, cache_dir: Optional[Path] = None):
        self.dir = Path(cache_dir or os.environ.get("AI_ROUTER_CACHE_DIR") or DEFAULT_CACHE_DIR)
        self.dir.mkdir(parents=True, exist_ok=True)

    def key(
        self,
        tier: int,
        task: str,
        system: Optional[str],
        prompt: str,
        images: Optional[list],
        json_mode: bool,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        h = hashlib.sha256()
        for chunk in (
            CACHE_SCHEMA,
            f"tier={tier}",
            f"task={task or ''}",
            f"system={system or ''}",
            prompt,
            f"json={json_mode}",
            f"temp={temperature}",
            f"maxtok={max_tokens}",
        ):
            h.update(chunk.encode("utf-8", "replace"))
            h.update(b"\x00")
        for img in images or []:
            h.update(_file_sha256(Path(img)).encode())
            h.update(b"\x00")
        return h.hexdigest()

    def path_for(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str) -> Optional[dict]:
        p = self.path_for(key)
        if not p.is_file():
            return None
        try:
            entry = json.loads(p.read_text())
        except json.JSONDecodeError:
            p.unlink(missing_ok=True)
            return None
        entry["cache_hit"] = True
        return entry

    def put(self, entry: dict) -> None:
        p = self.path_for(entry["cache_key"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=1))
        os.replace(tmp, p)

    def stats(self) -> dict:
        files = sorted(self.dir.glob("*.json"))
        entries, tokens_saved, by_backend = 0, 0, {}
        for f in files:
            try:
                e = json.loads(f.read_text())
            except json.JSONDecodeError:
                continue
            entries += 1
            by_backend[e.get("backend", "?")] = by_backend.get(e.get("backend", "?"), 0) + 1
            u = e.get("usage") or {}
            tokens_saved += (u.get("total_tokens") or 0) + (u.get("promptTokenCount") or 0)
        return {
            "cache_dir": str(self.dir),
            "entries": entries,
            "by_backend": by_backend,
            "usage_tokens_recorded": tokens_saved,
            "note": "every future cache HIT of these entries spends 0 tokens",
        }


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
class RouteResult(dict):
    """Dict-like result so `out['text']` and `out.text` both work."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc


class Router:
    def __init__(self, cache_dir: Optional[Path] = None, verbose: bool = True):
        self.key, self.key_source = load_google_key()
        self.cache = DiskCache(cache_dir)
        self.verbose = verbose
        self._google_disabled_reason: Optional[str] = None
        self._zai_disabled = os.environ.get("AI_ROUTER_NO_ZAI") == "1"
        self._gemini_disabled = os.environ.get("AI_ROUTER_NO_GEMINI") == "1"

    # -- public API ---------------------------------------------------------
    def generate(
        self,
        prompt: str,
        images: Optional[list] = None,
        tier: int = 3,
        task: str = "",
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        thinking_budget: Optional[int] = None,  # None = tier default; >=1 explicit
        use_cache: bool = True,
        refresh: bool = False,
    ) -> RouteResult:
        if tier not in TIERS:
            raise ValueError(f"tier must be one of {sorted(TIERS)}")
        spec = TIERS[tier]
        images = [Path(i) for i in (images or [])]
        for img in images:
            if not img.is_file():
                raise FileNotFoundError(f"image not found: {img}")

        key = self.cache.key(tier, task, system, prompt, images, json_mode, temperature, max_tokens)

        # ---- TIER 0: disk cache -------------------------------------------
        if use_cache and not refresh:
            hit = self.cache.get(key)
            if hit is not None:
                hit["latency_s"] = 0.0
                hit["replayed_from"] = hit.get("timestamp")
                if self.verbose:
                    print(f"[router] TIER 0 cache HIT (0 tokens): {key[:16]}…", file=sys.stderr)
                return RouteResult(hit)

        # ---- Google chain --------------------------------------------------
        trace: list[dict] = []
        started = time.time()
        text = usage = model = backend = None
        if not self._gemini_disabled and self.key and not self._google_disabled_reason:
            for m in spec.models:
                if self._google_disabled_reason:
                    trace.append({"attempt": f"gemini:{m}", "skipped": self._google_disabled_reason})
                    continue
                t0 = time.time()
                try:
                    out = _gemini_call(
                        model=m,
                        key=self.key,
                        prompt=prompt,
                        images=images,
                        system=system,
                        json_mode=json_mode,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        thinking_budget=thinking_budget if thinking_budget is not None else spec.thinking_budget,
                        timeout_s=spec.timeout_s,
                    )
                    text, usage, model, backend = out["text"], out["usage"], out["model"], "gemini"
                    trace.append({"attempt": f"gemini:{m}", "ok": True, "latency_s": round(time.time() - t0, 2)})
                    break
                except GeminiError as exc:
                    reason = exc.reason
                    trace.append(
                        {"attempt": f"gemini:{m}", "ok": False, "reason": reason, "latency_s": round(time.time() - t0, 2)}
                    )
                    low = reason.lower()
                    if any(mk in low for mk in GEO_BLOCK_MARKERS):
                        self._google_disabled_reason = "geo-block (FAILED_PRECONDITION) — skipping remaining Google models"
                        trace.append({"info": self._google_disabled_reason})
                    elif exc.http_code == 401 or "api key not valid" in low:
                        self._google_disabled_reason = "invalid Google key — skipping remaining Google models"
                    elif exc.retryable:  # one same-model retry for transient 5xx/network
                        time.sleep(1.5)
                        try:
                            out = _gemini_call(
                                model=m, key=self.key, prompt=prompt, images=images, system=system,
                                json_mode=json_mode, temperature=temperature, max_tokens=max_tokens,
                                thinking_budget=thinking_budget if thinking_budget is not None else spec.thinking_budget,
                                timeout_s=spec.timeout_s,
                            )
                            text, usage, model, backend = out["text"], out["usage"], out["model"], "gemini"
                            trace.append({"attempt": f"gemini:{m} (retry)", "ok": True})
                            break
                        except GeminiError as exc2:
                            trace.append({"attempt": f"gemini:{m} (retry)", "ok": False, "reason": exc2.reason})
        elif not self.key:
            trace.append({"info": "no GOOGLE_API_KEY (env/.env) — Google tiers inactive"})

        # ---- z-ai floor -----------------------------------------------------
        if text is None:
            if self._zai_disabled:
                raise RuntimeError("all backends failed (z-ai disabled): " + json.dumps(trace))
            t0 = time.time()
            try:
                out = _zai_call(
                    prompt=prompt,
                    images=images,
                    system=system,
                    vision_mode=spec.zai_chat_or_vision == "vision",
                    timeout_s=spec.zai_timeout_s,
                )
                text, usage, model, backend = out["text"], out["usage"], out["model"], "zai"
                trace.append({"attempt": "z-ai:" + spec.zai_chat_or_vision, "ok": True, "latency_s": round(time.time() - t0, 2)})
            except GeminiError as exc:
                trace.append({"attempt": "z-ai:" + spec.zai_chat_or_vision, "ok": False, "reason": exc.reason})
                raise RuntimeError("all backends failed: " + json.dumps(trace)) from exc

        entry = {
            "schema": CACHE_SCHEMA,
            "cache_key": key,
            "timestamp": _now_iso(),
            "tier": tier,
            "tier_name": spec.name,
            "task": task or "",
            "backend": backend,
            "model": model,
            "text": text,
            "usage": usage,
            "fallback_trace": trace,
            "latency_s": round(time.time() - started, 2),
            "cache_hit": False,
            "image_sha256": [_file_sha256(i) for i in images],
            "json_mode": json_mode,
        }
        if use_cache:
            self.cache.put(entry)
        entry["cache_hit"] = False
        if self.verbose:
            print(f"[router] TIER {tier} → {backend}:{model} in {entry['latency_s']}s "
                  f"(cache {'written' if use_cache else 'bypassed'})", file=sys.stderr)
        return RouteResult(entry)

    # convenience wrappers matching the law
    def tier1_spatial(self, prompt, **kw) -> RouteResult:
        return self.generate(prompt, tier=1, task=kw.pop("task", "spatial"), **kw)

    def tier2_persian_qa(self, prompt, **kw) -> RouteResult:
        return self.generate(prompt, tier=2, task=kw.pop("task", "persian_qa"), **kw)

    def tier3_smoke(self, prompt, **kw) -> RouteResult:
        return self.generate(prompt, tier=3, task=kw.pop("task", "smoke"), **kw)


# --------------------------------------------------------------------------- #
# --probe : the repeatable Step-1.1 key/model audit
# --------------------------------------------------------------------------- #
def run_probe() -> dict:
    import platform

    r = requests  # type: ignore
    key, source = load_google_key()
    report: dict[str, Any] = {
        "schema": "panodrome.ai_router.probe.v1",
        "timestamp": _now_iso(),
        "python": platform.python_version(),
        "key": {"present": bool(key), "source": source, "masked": _mask(key)},
        "requests_lib": requests is not None,
        "auth_matrix": {},
        "model_tests": {},
        "egress": {},
        "zai": {},
        "sdk": {},
        "verdict": {},
    }

    # egress context (why geo-block, if geo-blocked)
    try:
        ip = r.get("https://ipinfo.io/json", timeout=10).json()
        report["egress"] = {k: ip.get(k) for k in ("ip", "city", "country", "org")}
    except Exception as exc:
        report["egress"] = {"error": type(exc).__name__}

    # auth matrix against ListModels
    if key:
        url_q = f"{GEMINI_BASE}/models?pageSize=5"
        tests = {
            "x-goog-api-key header": dict(url=url_q, headers={"x-goog-api-key": key}),
            "?key= query param": dict(url=f"{GEMINI_BASE}/models?key={key}&pageSize=5", headers={}),
            "Authorization: Bearer": dict(url=url_q, headers={"Authorization": f"Bearer {key}"}),
            "control: garbage key": dict(url=url_q, headers={"x-goog-api-key": "AQ.INVALIDgarbage123"}),
        }
        for name, spec in tests.items():
            try:
                resp = r.get(spec["url"], headers=spec["headers"], timeout=20)
                body = {}
                try:
                    body = resp.json()
                except Exception:
                    pass
                err = body.get("error", {})
                entry = {
                    "http": resp.status_code,
                    "status": err.get("status", "OK"),
                    "message": (err.get("message") or "models listed")[:120],
                }
                if resp.status_code == 200:
                    names = [m.get("name", "").split("/")[-1] for m in body.get("models", [])]
                    entry["sample_models"] = names
                report["auth_matrix"][name] = entry
            except Exception as exc:
                report["auth_matrix"][name] = {"error": type(exc).__name__}

        # per-model generateContent smoke
        for m in PROBE_MODELS:
            try:
                out = _gemini_call(
                    model=m, key=key, prompt="Reply with exactly: ROUTER-PROBE-OK",
                    images=None, system=None, json_mode=False, temperature=0,
                    max_tokens=None, thinking_budget=None, timeout_s=60,
                )
                report["model_tests"][m] = {"ok": True, "text": out["text"][:60], "usage": out["usage"]}
            except GeminiError as exc:
                report["model_tests"][m] = {"ok": False, "reason": exc.reason[:200]}

    # google-genai SDK (optional)
    try:
        from google import genai  # type: ignore

        client = genai.Client(api_key=key) if key else None
        if client:
            resp = client.models.generate_content(
                model="gemini-3.8-flash", contents="Reply with exactly: SDK-PROBE-OK"
            )
            report["sdk"] = {"installed": True, "ok": True, "text": (resp.text or "")[:60]}
    except Exception as exc:
        msg = str(exc)
        report["sdk"] = {
            "installed": True,
            "ok": False,
            "error": (msg.split("\n")[0])[:200],
            "geo_blocked": any(mk in msg.lower() for mk in GEO_BLOCK_MARKERS),
        }
        try:
            import google.genai as gg  # noqa

            report["sdk"]["version"] = getattr(gg, "__version__", "unknown")
        except Exception:
            pass

    # z-ai floors
    for name, cmd in (
        ("chat", ["z-ai", "chat", "-p", "Reply with exactly: ZAI-PROBE-OK", "-o", "/tmp/_probe_zai.json"]),
        ("vision", ["z-ai", "vision", "-p", "Reply with exactly: ZAI-VISION-OK", "-o", "/tmp/_probe_zai_v.json"]),
    ):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            data = json.loads(Path("/tmp/_probe_zai.json" if name == "chat" else "/tmp/_probe_zai_v.json").read_text())
            report["zai"][name] = {"ok": proc.returncode == 0, "model": data.get("model"), "text": data["choices"][0]["message"]["content"][:60]}
        except Exception as exc:
            report["zai"][name] = {"ok": False, "error": type(exc).__name__}

    # verdict — differential key proof via the SAME method (x-goog-api-key):
    # garbage key MUST 401, our key must NOT. (The Bearer 401 is a wrong-method
    # error for AI Studio keys, NOT evidence about key validity.)
    garbage = report["auth_matrix"].get("control: garbage key", {}) or {}
    ours = [
        v for k, v in report["auth_matrix"].items()
        if k == "x-goog-api-key header" and isinstance(v, dict)
    ]
    key_valid = (
        garbage.get("http") == 401
        and all(v.get("http") != 401 for v in ours)
    )
    low_all = json.dumps(report).lower()
    geo = "location is not supported" in low_all
    quota_zero = "limit: 0" in low_all or "your current quota" in low_all
    gemini_ok = any(t.get("ok") for t in report["model_tests"].values())
    zai_ok = report["zai"].get("chat", {}).get("ok")
    if gemini_ok:
        mode = "full 4-tier chain (Gemini callable from this egress)"
    elif geo or quota_zero:
        mode = ("z-ai-only from this egress — Gemini key VALID but geo-blocked (flash) "
                "and/or free-tier quota 0 (pro); tiers stay armed for supported regions")
    else:
        mode = "z-ai-only (Gemini unreachable)"
    report["verdict"] = {
        "key_valid": key_valid,
        "key_proof": "garbage key -> 401 'API key not valid' while our key passes auth "
                     "(400 geo-block / 404 deprecation / 429 quota are all POST-auth errors)",
        "gemini_callable_from_here": gemini_ok,
        "geo_blocked": geo,
        "quota_zero_on_free_tier": quota_zero,
        "zai_floor_ok": zai_ok,
        "router_mode": mode,
    }
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Panodrome Smart Model Router (4-Tier Law)")
    ap.add_argument("--probe", action="store_true", help="audit key auth matrix + model access + z-ai floors")
    ap.add_argument("--cache-stats", action="store_true")
    ap.add_argument("--tier", type=int, choices=sorted(TIERS), help="tier 1|2|3 (law in CLAUDE.md)")
    ap.add_argument("-p", "--prompt", help="prompt text")
    ap.add_argument("-i", "--image", action="append", default=[], help="image path (repeatable)")
    ap.add_argument("-s", "--system", help="system prompt")
    ap.add_argument("--task", default="", help="task label for cache bookkeeping")
    ap.add_argument("--json-out", action="store_true", help="print full result JSON")
    ap.add_argument("--json-mode", action="store_true", help="ask Gemini for application/json output")
    ap.add_argument("--no-cache", action="store_true", help="bypass cache read+write")
    ap.add_argument("--refresh", action="store_true", help="ignore cache read, overwrite entry")
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--thinking-budget", type=int, default=None,
                    help="send thinkingConfig.thinkingBudget (>=1 only; 0 is rejected by flash-lite)")
    args = ap.parse_args(argv)

    if args.probe:
        print(json.dumps(run_probe(), ensure_ascii=False, indent=1))
        return 0
    if args.cache_stats:
        print(json.dumps(DiskCache().stats(), ensure_ascii=False, indent=1))
        return 0
    if not (args.tier and args.prompt):
        ap.error("--tier and --prompt are required (or use --probe / --cache-stats)")
        return 3

    router = Router()
    try:
        out = router.generate(
            prompt=args.prompt,
            images=args.image or None,
            tier=args.tier,
            task=args.task,
            system=args.system,
            json_mode=args.json_mode,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            thinking_budget=args.thinking_budget,
            use_cache=not args.no_cache,
            refresh=args.refresh,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    if args.json_out:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(out["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
