# AGENT BOOT — Panodrome (read this before anything else)

You are the agent building **Panodrome** — repo `mohammadaliaghaabbasi/3d-idea`.

## Boot protocol (every turn)

1. Read **`MEMORY_STATE.json`** (root, ≤50 lines). It contains: locked decisions, current phase, completed modules, skills status, active decisions, and `next_immediate_action`.
2. Execute `next_immediate_action`. Do NOT re-read `docs/*` to reconstruct context — `docs/` is an archive.
3. When done: update `MEMORY_STATE.json` (phase progress, modules, next action) and commit with a prefixed message (`phase1:` `memory:` `skill:` `docs:`).

## Hard rules

- **Memory Iron Law:** `MEMORY_STATE.json` at start & end of every turn. Full policy in `CLAUDE.md`.
- **Single source of truth (Anti-Fragmentation Lock 2026-11-02):** all work happens ONLY in `mohammadaliaghaabbasi/3d-idea` (private). `panodrome` (public) is a deploy-only Pages mirror — never clone or hand-edit it; only `scripts/deploy_gh_pages.sh` writes it.
- **Never revisit locked decisions:** Panodrome · EN-first + FA RTL · Three.js + GSAP + PolyHaven CC0 · direct Phase 1.
- **Never store credentials.** GitHub token comes only via env var `T` (see `scripts/publish_*.sh`).
- **Bilingual everything:** UI + metadata always EN + FA (RTL).
- **CC0 content only**; always credit creators.
