#!/usr/bin/env python3
"""Patch skills/ai_router.py — part B: generate() backend ordering + quota cap
+ compressed Gemini images + T3 default max_tokens + CLI --stats/--cap-reset."""
import sys
from pathlib import Path

P = Path("/home/z/my-project/3d-idea/skills/ai_router.py")
src = P.read_text()

def replace(start_marker: str, end_marker: str, new: str, tag: str, keep_end=True):
    global src
    i = src.find(start_marker)
    if i < 0:
        sys.exit(f"PATCH FAIL {tag}: start marker not found")
    j = src.find(end_marker, i + len(start_marker))
    if j < 0:
        sys.exit(f"PATCH FAIL {tag}: end marker not found")
    src = src[:i] + new + (src[j:] if keep_end else src[j + len(end_marker):])
    print(f"  ok: {tag}")

# ------------------------------------------------ 1) T3 default max_tokens (before cache key)
old = '''        spec = TIERS[tier]
        images = [Path(i) for i in (images or [])]'''
new = '''        spec = TIERS[tier]
        if max_tokens is None and spec.default_max_tokens is not None:
            max_tokens = spec.default_max_tokens   # T3 law: 512-token ceiling
        images = [Path(i) for i in (images or [])]'''
if src.count(old) != 1:
    sys.exit("PATCH FAIL: spec/images anchor not unique")
src = src.replace(old, new)
print("  ok: T3 default max_tokens")

# ------------------------------------------------ 2) backend ordering + quota + images
new_chain = '''        # ---- backends (T3 law: z-ai CLI FIRST, 0 Gemini quota) ----------
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

'''
replace("        # ---- Google chain ---",
        '        entry = {\n            "schema": CACHE_SCHEMA,',
        new_chain, "backend ordering + quota + image economy")

# ------------------------------------------------ 3) CLI: --stats / --cap-reset
old = '''    ap.add_argument("--cache-stats", action="store_true")'''
new = '''    ap.add_argument("--cache-stats", action="store_true")
    ap.add_argument("--stats", action="store_true", help="cache + live-quota ledger report (token economy)")
    ap.add_argument("--cap-reset", action="store_true", help="reset the live-call quota ledger")'''
if src.count(old) != 1:
    sys.exit("PATCH FAIL: CLI anchor not unique")
src = src.replace(old, new)
print("  ok: CLI flags")

old = '''    if not (args.tier and args.prompt):
        ap.error("--tier and --prompt are required (or use --probe / --cache-stats)")
        return 3'''
new = '''    if args.cap_reset:
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
        return 3'''
if src.count(old) != 1:
    sys.exit("PATCH FAIL: CLI handling anchor not unique")
src = src.replace(old, new)
print("  ok: CLI handling")

# ------------------------------------------------ 4) usage docstring line
old = '''  CLI:  python3 skills/ai_router.py --probe'''
new = '''  CLI:  python3 skills/ai_router.py --stats        (token-economy report)
        python3 skills/ai_router.py --cap-reset    (clear the live-call cap)
        python3 skills/ai_router.py --probe'''
if src.count(old) != 1:
    sys.exit("PATCH FAIL: usage docstring anchor not unique")
src = src.replace(old, new)
print("  ok: usage docstring")

P.write_text(src)
print("router patch B OK")
