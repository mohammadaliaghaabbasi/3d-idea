# agent-work — per-agent research & delivery logs

Several people/agents work on Panodrome at the same time. To keep parallel work
auditable and mergeable into one final report, **every session keeps its own log
here, on its own branch**, and never rewrites another session's entry.

## Convention

```
docs/agent-work/<YYYY-MM-DD>-<slug>/
    README.md           what this session set out to do, what shipped, what is open
    research.md         external sources examined + the facts extracted (with URLs)
    measurements.json   every number the session produced, machine-readable
    verification.md     the exact commands run and what they returned
    INVENTORY.md        files added/changed + commit SHAs
    artifacts/          screenshots, logs, small JSON dumps (keep < 5 MB each)
```

Branches: `agent/<agent>/<YYYY-MM-DD>-<slug>` cut from the `main` the session
started on. Push the branch **and** the resulting `main` commit, so the final
report can be assembled from either.

Rules
- One folder per session. Never edit a folder that is not yours.
- Numbers go in `measurements.json` *and* in prose; a claim without a number is
  not a measurement.
- Anything that could not be verified is listed under "Not verified" — never
  quietly dropped.
- Keep binaries out; link to the live URL or the repo path instead.

## Sessions

| Date | Agent | Slug | Topic |
|---|---|---|---|
| 2026-11-12 | Buffy | `2026-11-12-splat-parity` | Why the walk view blurs, photographic-density bake, SPZ + 4-level LOD, moradi page policy |
