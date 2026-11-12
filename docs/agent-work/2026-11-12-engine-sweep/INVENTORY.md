# Inventory — engine-sweep (2026-11-12)

This session is **additive**: no file owned by another team was modified.

## Added

| File | Role |
|---|---|
| `skills/engine_sweep.py` | The sweep harness: `--group moradi|houses|villa`, SPZ v4 (zstd) + v2 (gzip) readers, ERP coverage test, JSON writer |
| `skills/collision_probe.py` | Faithful Python mirror of `public/js/collider.js::resolve()` with post-resolve metrics (egress, outside distance, residual overlap) |
| `docs/agent-work/2026-11-12-engine-sweep/results.json` | Full machine-readable results (10 + 10 + 1 rows) |
| `docs/agent-work/2026-11-12-engine-sweep/README.md` | Findings and tables |
| `docs/agent-work/2026-11-12-engine-sweep/verification.md` | Commands, container discovery, outputs, what was not verified |
| `docs/agent-work/2026-11-12-engine-sweep/INVENTORY.md` | This file |

## Changed

| File | Change |
|---|---|
| `docs/agent-work/README.md` | Session table gained the `2026-11-12-engine-sweep` row (my own index file) |

## Read only (no edits)

`public/js/collider.js` (mirrored logic), `public/data/rooms_db.json`,
`docs/rd-artifacts/true3d/villa_room.json`, `public/labs/engine-v1/app.js`
(asset naming), live assets under `panodrome/labs/engine-v1/assets/**`.

## Runtime note

`python3 -m pip install zstandard` was installed into the workspace venv to decode
SPZ v4. It is a decode-only dependency of the harness; nothing in `public/` or in
the deploy path changed, so no redeploy was needed for this session.

## Reproduce

```bash
python3 skills/engine_sweep.py --group moradi          # ~4 min, downloads ~160 MB
python3 skills/engine_sweep.py --group houses          # seconds
python3 skills/engine_sweep.py --group villa           # seconds
```
