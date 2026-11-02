# AGENT BOOT — Panodrome (read this before anything else)

You are the agent building **Panodrome** — repo `mohammadaliaghaabbasi/3d-idea`.

## Boot protocol (every turn)

1. Read **`MEMORY_STATE.json`** (root, ≤50 lines). It contains: locked decisions, current phase, completed modules, skills status, active decisions, and `next_immediate_action`.
2. Execute `next_immediate_action`. Do NOT re-read `docs/*` to reconstruct context — `docs/` is an archive.
3. When done: update `MEMORY_STATE.json` (phase progress, modules, next action) and commit with a prefixed message (`phase1:` `memory:` `skill:` `docs:`).

## Hard rules

- **Memory Iron Law:** `MEMORY_STATE.json` at start & end of every turn. Full policy in `CLAUDE.md`.
- **Single source of truth (Anti-Fragmentation Lock 2026-11-02):** all work happens ONLY in `mohammadaliaghaabbasi/3d-idea` (private). `panodrome` (public) is a deploy-only Pages mirror — never clone or hand-edit it; only `scripts/deploy_gh_pages.sh` writes it.
- **Never revisit locked decisions:** Panodrome · EN-first + FA RTL · Three.js + GSAP + PolyHaven CC0/Wikimedia · direct Phase 1.
- **Never store credentials.** GitHub token comes only via env var `T` (see `scripts/publish_*.sh`).
- **Bilingual everything:** UI + metadata always EN + FA (RTL).
- **CC0/CC-BY-SA content only**; always credit creators.
- **Stage gate:** Stage 1.5 delivered (true first-person walk). Stages 2–5 remain LOCKED until the owner approves Stage 1.5 on the live URL. Walking = real translation with sliding collision on the room volume — NEVER vertex displacement, NEVER FOV zoom (fov fixed 68/75). Flat floor + plumb walls forever. Vazirmatn always. No naked-oscillator footsteps.
