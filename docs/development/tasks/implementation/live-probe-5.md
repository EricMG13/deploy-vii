# Live batch probe-5

- Command: probe
- Pool: user-selected (coordinator ruling 22 October 2026)
- Seed: 696993519
- Cap: 4 USD; reserved 0, spent 0.8039935, remaining 3.1960065
- Catalog: `openrouter-models-2026-10-21.json`, the coordinator's saved models file (not in the repository; sha256 b17fc211fe65e4347e6808adbb2d35b4d2106aca90e690a81fcc5e66c6b89c9f), looked up 2026-10-22T03:37:47Z
- Registry modules with a live step contract: 2 of 25
- Max tokens: 32000 per call (every model)
- Cells planned: 2; steps run: 2; not authorized by CP-0: 0
- Stopped: no

## Pool

| Model | Eligible | Reason | Requested effort | Effort sent | Reserved USD per attempt (largest) |
| --- | --- | --- | --- | --- | --- |
| google/gemini-4-argon | yes |  | xhigh | high (mapped) | 0.900700 |

## Steps

| Cell | Case | Step | Model | Seed | Attempt | Status | Class | USD | Issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| probe-00 | probe | source_readiness | google/gemini-4-argon | 696993519 | a3392cdd-1f91-4b71-bbf8-67ce85a441f2-source_readiness-1 | rejected | ok | 0.526488 | 4 |
| probe-01 | probe | source_readiness | google/gemini-4-argon | 696993520 | 50115c10-121b-4be2-9b91-1aeb02a78d1f-source_readiness-1 | rejected | ok | 0.2775055 | 3 |

## Cohorts

| Cohort | Attempts | Accepted | Rejected | Pooled | Qualification |
| --- | --- | --- | --- | --- | --- |
| openrouter-pool | 2 | 0 | 2 | yes | not decided here |
