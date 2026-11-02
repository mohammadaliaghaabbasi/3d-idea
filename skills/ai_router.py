#!/usr/bin/env python3
"""
Panodrome Smart Model Router — skills/ai_router.py
=================================================
ONE unified entry point for every AI call in this repo. Enforces the
4-Tier Model Selection Law (locked in CLAUDE.md / .cursorrules /
MEMORY_STATE.json) with disk caching for ZERO wasted tokens.

THE 4-TIER LAW (owner revision 2026-11-02 — TOKEN ECONOMY EDITION)
------------------------------------------------------------------
  TIER 0  Disk cache (`.cache/ai_responses/`) — checked FIRST, every
          call, text or vision: hash (tier, task, system, prompt,
          image_sha256, json, temp, maxtok) → instant replay, 0 tokens.
  TIER 1  Lead 3D Spatial Architect & Final Visual QA Judge —
          `gemini-3.6-flash` ONLY: (a) 3D reconstruction math /
          calibration / furniture bounding volumes from panoramas,
          (b) auditing final rendered screenshots. Fallback: z-ai.
  TIER 2  Fast structured JSON & copywriting — `gemini-3.5-flash`,
          auto-fallback `gemini-3.5-flash-lite` → z-ai. Input images are
          compressed to ≤1024px long-edge JPEG q82 before sending
          (~70% image-token reduction).
  TIER 3  Routine coding / bulk checks / simple text — **z-ai CLI by
          default (0 cost to the Gemini quota)**; gemini-3.5-flash-lite
          only as fallback with maxOutputTokens 512.

QUOTA GUARDS (hard, always on):
  · Live-call cap: max 15 live Gemini HTTP calls in a rolling 6h
    window (ledger `.cache/ai_router_ledger.json`; env AI_ROUTER_CALL_CAP
    overrides; `--cap-reset` clears). Over cap → Google is skipped and
    the call falls straight to the z-ai floor.
  · Every attempt (success or failure) is recorded with its token usage;
    `--stats` prints the cache + quota report.

FALLBACK TRIGGERS (auto, per law): HTTP 429 / 403 quota, 400
FAILED_PRECONDITION (geo-block), 401, network timeout, 5xx after one
retry → walk down the chain, ending at the local `z-ai` CLI.
Geo-block (FAILED_PRECONDITION "User location") disables the Google
backends for the rest of the process — no pointless retries.

SECURITY: the Google AI Studio key lives ONLY in `.env` (git-ignored)
or the GOOGLE_API_KEY env var. It is NEVER written to any tracked
file, log line, or cache entry.

GEO-BYPASS GATEWAY: set GEMINI_PROXY_URL in `.env` (e.g. the deployed
Cloudflare Worker gateway — scripts/cf_deploy_gateway.sh) and every
Gemini call is routed through its North-America-pinned Durable Object
(locationHint "enam"), so egress regions on Google's unsupported list
(HK build sandbox, Iran) stop hitting "User location is not supported".
Unset -> direct generativelanguage.googleapis.com access.

USAGE
-----
  CLI:  python3 skills/ai_router.py --stats        (token-economy report)
        python3 skills/ai_router.py --cap-reset    (clear the live-call cap)
        python3 skills/ai_router.py --probe
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
# Gateway state, measured live 2026-11-02 through the CF gateway:
#   WORKS on free tier: 3.6-flash, 3.5-flash, 3.5-flash-lite
#   429 quota-0: 3.8-flash, flash-latest, pro-latest, 3.1-pro-preview
#   503 busy (transient): 3.7-flash, 3.1-flash-lite
_PROXY_BASE_CACHE: dict = {}


def _load_env_var(name: str) -> Optional[str]:
    """Env var or .env value (never logged, never hardcoded)."""
    val = os.environ.get(name)
    if val:
        return val.strip()
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith(name) and "=" in line:
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    return None


def gemini_base() -> str:
    """Effective Generative Language base URL (GEMINI_PROXY_URL-aware)."""
    if "v" not in _PROXY_BASE_CACHE:
        proxy = _load_env_var("GEMINI_PROXY_URL")
        if proxy:
            proxy = proxy.rstrip("/")
            if not proxy.startswith(("http://", "https://")):
                proxy = "https://" + proxy
            _PROXY_BASE_CACHE["v"] = proxy + "/v1beta"
        else:
            _PROXY_BASE_CACHE["v"] = GEMINI_BASE
    return _PROXY_BASE_CACHE["v"]
# Current ladder, MEASURED 2026-11-02: the 2.5/2.0 family returns 404
# "no longer available to new users" and points at these 3.x successors:
#   gemini-2.5-pro       -> gemini-3.1-pro-preview
#   gemini-2.5-flash     -> gemini-3.8-flash
#   gemini-2.5-flash-lite-> gemini-3.5-flash-lite
#   gemini-2.0-flash     -> gemini-3.8-flash
PROBE_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
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
    prefer_zai: bool = False          # T3 law: z-ai CLI FIRST (0 Gemini quota)
    default_max_tokens: Optional[int] = None  # applied when caller passes None


TIERS: dict[int, TierSpec] = {
    # Tier→role mapping is the OWNER'S LAW (CLAUDE.md); ladders re-assigned
    # 2026-11-02 (token-economy edition, owner directive):
    #   T1 = gemini-3.6-flash ONLY (lead 3D architect + final visual QA judge)
    #   T2 = gemini-3.5-flash -> 3.5-flash-lite (fast JSON / copy, 1024px imgs)
    #   T3 = z-ai CLI by default; gemini-3.5-flash-lite fallback, 512 tokens
    1: TierSpec(
        number=1,
        name="lead_3d_architect_and_qa_judge",
        desc="3D spatial-reconstruction math & calibration, furniture "
             "bounding volumes from panoramas, FINAL rendered-screenshot "
             "QA audit",
        models=["gemini-3.6-flash"],
        zai_chat_or_vision="vision",
        thinking_budget=None,
        timeout_s=180,
    ),
    2: TierSpec(
        number=2,
        name="fast_json_and_copy",
        desc="Fast structured JSON, copywriting, Persian text, routine "
             "vision checks (images auto-compressed to 1024px q82)",
        models=["gemini-3.5-flash", "gemini-3.5-flash-lite"],
        zai_chat_or_vision="vision",
        thinking_budget=None,
        timeout_s=120,
    ),
    3: TierSpec(
        number=3,
        name="bulk_smoke",
        desc="Routine coding help, bulk checks, simple text — z-ai CLI by "
             "default (0 Gemini quota); flash-lite fallback capped at 512 "
             "output tokens",
        models=["gemini-3.5-flash-lite"],
        zai_chat_or_vision="chat",
        thinking_budget=None,
        timeout_s=60,
        prefer_zai=True,
        default_max_tokens=512,
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


# --------------------------------------------------------------------------- #
# QUOTA GUARD — rolling live-call ledger (owner law: max 15 live Gemini
# calls per rolling 6h window). Cache hits & z-ai calls are free, never
# recorded. Env AI_ROUTER_CALL_CAP overrides; --cap-reset clears.
# --------------------------------------------------------------------------- #
DEFAULT_LEDGER = REPO_ROOT / ".cache" / "ai_router_ledger.json"
CALL_CAP_DEFAULT = 15
CALL_WINDOW_S = 6 * 3600


class QuotaLedger:
    def __init__(self, path: Path = DEFAULT_LEDGER):
        self.path = Path(path)
        self.cap = int(os.environ.get("AI_ROUTER_CALL_CAP", CALL_CAP_DEFAULT))
        self.window_s = CALL_WINDOW_S

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
            if isinstance(d.get("calls"), list):
                return d
        except Exception:
            pass
        return {"calls": []}

    def _save(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False))
        os.replace(tmp, self.path)

    def calls_in_window(self) -> list:
        now = time.time()
        return [c for c in self._load()["calls"] if now - c.get("ts", 0) < self.window_s]

    def exhausted(self) -> bool:
        return len(self.calls_in_window()) >= self.cap

    def record(self, model: str, tier: int, ok: bool, usage: Optional[dict] = None) -> None:
        d = self._load()
        d["calls"].append({
            "ts": time.time(), "iso": _now_iso(), "model": model,
            "tier": tier, "ok": bool(ok),
            "tokens": sum(v for v in (usage or {}).values() if isinstance(v, int)),
        })
        self._save(d)

    def reset(self) -> None:
        self._save({"calls": []})

    def stats(self) -> dict:
        w = self.calls_in_window()
        by_model: dict = {}
        for c in w:
            by_model[c.get("model", "?")] = by_model.get(c.get("model", "?"), 0) + 1
        return {
            "live_calls_in_window": len(w),
            "cap": self.cap,
            "window_hours": self.window_s / 3600,
            "by_model": by_model,
            "tokens_spent_in_window": sum(c.get("tokens", 0) for c in w),
            "ledger": str(self.path),
        }


# --------------------------------------------------------------------------- #
# IMAGE ECONOMY — compress to <=1024px long-edge JPEG q82 before sending to
# Gemini (~70% image-token reduction, owner law 2026-11-02). Originals are
# untouched (cache keys stay stable); z-ai keeps the originals.
# --------------------------------------------------------------------------- #
_IMG_ECONOMY_DIR = DEFAULT_CACHE_DIR / "img1024"


def _gemini_image(path: Path) -> Path:
    try:
        from PIL import Image

        src = Image.open(path)
        src.load()
        w, h = src.size
        if max(w, h) <= 1024 and path.suffix.lower() in (".jpg", ".jpeg"):
            return path
        out_path = _IMG_ECONOMY_DIR / (path.stem + "_" + _file_sha256(path)[:10] + ".jpg")
        if out_path.is_file():
            return out_path
        _IMG_ECONOMY_DIR.mkdir(parents=True, exist_ok=True)
        im = src.convert("RGB")
        scale = 1024.0 / max(w, h)
        if scale < 1.0:
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        im.save(out_path, "JPEG", quality=82)
        return out_path
    except Exception:
        return path  # economy must never break a call



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
    url = f"{gemini_base()}/models/{model}:generateContent"
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
        if max_tokens is None and spec.default_max_tokens is not None:
            max_tokens = spec.default_max_tokens   # T3 law: 512-token ceiling
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

        # ---- backends (T3 law: z-ai CLI FIRST, 0 Gemini quota) ----------
        trace: list[dict] = []
        started = time.time()
        text = usage = model = backend = None
        ledger = QuotaLedger()

        def google_chain() -> None:
            nonlocal text, usage, model, backend
            if self._gemini_disabled:
                trace.append({"info": "gemini disabled by env (AI_ROUTER_NO_GEMINI)"})
                return
            if not self.key:
                trace.append({"info": "no GOOGLE_API_KEY (env/.env) — Google tiers inactive"})
                return
            if self._google_disabled_reason:
                trace.append({"attempt": "gemini", "skipped": self._google_disabled_reason})
                return
            if ledger.exhausted():
                trace.append({"info": f"QUOTA CAP: {ledger.cap} live Gemini calls in the last "
                                       f"{ledger.window_s / 3600:.0f}h — Google skipped, z-ai floor"})
                return
            gimgs = [_gemini_image(i) for i in images]   # <=1024px q82 economy
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
                        images=gimgs,
                        system=system,
                        json_mode=json_mode,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        thinking_budget=thinking_budget if thinking_budget is not None else spec.thinking_budget,
                        timeout_s=spec.timeout_s,
                    )
                    ledger.record(m, tier, True, out.get("usage"))
                    text, usage, model, backend = out["text"], out["usage"], out["model"], "gemini"
                    trace.append({"attempt": f"gemini:{m}", "ok": True, "latency_s": round(time.time() - t0, 2)})
                    return
                except GeminiError as exc:
                    ledger.record(m, tier, False)
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
                                model=m, key=self.key, prompt=prompt, images=gimgs, system=system,
                                json_mode=json_mode, temperature=temperature, max_tokens=max_tokens,
                                thinking_budget=thinking_budget if thinking_budget is not None else spec.thinking_budget,
                                timeout_s=spec.timeout_s,
                            )
                            ledger.record(m, tier, True, out.get("usage"))
                            text, usage, model, backend = out["text"], out["usage"], out["model"], "gemini"
                            trace.append({"attempt": f"gemini:{m} (retry)", "ok": True})
                            return
                        except GeminiError as exc2:
                            ledger.record(m, tier, False)
                            trace.append({"attempt": f"gemini:{m} (retry)", "ok": False, "reason": exc2.reason})

        def zai_floor(raise_on_fail: bool) -> bool:
            nonlocal text, usage, model, backend
            if self._zai_disabled:
                if raise_on_fail:
                    raise RuntimeError("all backends failed (z-ai disabled): " + json.dumps(trace))
                trace.append({"info": "z-ai disabled by env (AI_ROUTER_NO_ZAI)"})
                return False
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
                return True
            except GeminiError as exc:
                trace.append({"attempt": "z-ai:" + spec.zai_chat_or_vision, "ok": False, "reason": exc.reason})
                if raise_on_fail:
                    raise RuntimeError("all backends failed: " + json.dumps(trace)) from exc
                return False

        if spec.prefer_zai:
            zai_floor(raise_on_fail=False)      # T3: z-ai CLI by default
            if text is None:
                google_chain()                  # fallback: flash-lite (512-tok cap)
                if text is None:
                    zai_floor(raise_on_fail=True)
        else:
            google_chain()
            if text is None:
                zai_floor(raise_on_fail=True)

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
        "gateway": {},
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

    # gateway context (geo-bypass route, if configured)
    report["gateway"] = {
        "configured": bool(_load_env_var("GEMINI_PROXY_URL")),
        "base": gemini_base(),
        "direct": gemini_base() == GEMINI_BASE,
    }

    # auth matrix against ListModels
    if key:
        url_q = f"{gemini_base()}/models?pageSize=5"
        tests = {
            "x-goog-api-key header": dict(url=url_q, headers={"x-goog-api-key": key}),
            "?key= query param": dict(url=f"{gemini_base()}/models?key={key}&pageSize=5", headers={}),
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
        gw = report["gateway"].get("configured")
        mode = ("full 4-tier chain via Cloudflare gateway (geo-bypassed)" if gw
                else "full 4-tier chain (Gemini callable from this egress)")
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
    ap.add_argument("--stats", action="store_true", help="cache + live-quota ledger report (token economy)")
    ap.add_argument("--cap-reset", action="store_true", help="reset the live-call quota ledger")
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
    if args.cap_reset:
        QuotaLedger().reset()
        print("quota ledger reset (live-call cap window cleared)")
    if args.stats:
        print(json.dumps({
            "quota": QuotaLedger().stats(),
            "cache": DiskCache().stats(),
        }, ensure_ascii=False, indent=1))
        return 0
    if not (args.tier and args.prompt):
        ap.error("--tier and --prompt are required (or use --probe / --cache-stats / --stats)")
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
