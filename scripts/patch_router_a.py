#!/usr/bin/env python3
"""Patch skills/ai_router.py — token-economy edition (owner directive 2026-11-02).
Anchored replacements; verifies each patch; exits non-zero on any failure."""
import sys
from pathlib import Path

P = Path("/home/z/my-project/3d-idea/skills/ai_router.py")
src = P.read_text()

def replace(start_marker: str, end_marker: str, new: str, tag: str):
    global src
    i = src.find(start_marker)
    if i < 0:
        sys.exit(f"PATCH FAIL {tag}: start marker not found")
    j = src.find(end_marker, i + len(start_marker))
    if j < 0:
        sys.exit(f"PATCH FAIL {tag}: end marker not found")
    src = src[:i] + new + src[j:]
    print(f"  ok: {tag}")

# ---------------------------------------------------------------- 1) TierSpec + TIERS
new_tiers = '''@dataclass
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

'''
replace("@dataclass\nclass TierSpec:", "\n\n# --------------------------------------------------------------------------- #\n# Key handling",
        new_tiers, "TierSpec + TIERS ladders")

# ------------------------------------------------- 2) QuotaLedger + image economy
ledger_code = '''

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
            "tokens": (usage or {}).get("total_tokens") or 0,
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

'''
anchor = '''    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return data, mime
'''
assert src.count(anchor) == 1
src = src.replace(anchor, anchor + ledger_code)
print("  ok: QuotaLedger + image economy inserted")

P.write_text(src)
print("router patched OK")
