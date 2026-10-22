# Live batch probe-6

- Command: probe
- Pool: user-selected (coordinator ruling 22 October 2026)
- Seed: 1404762132
- Cap: 2 USD; reserved 0, spent 0.483321, remaining 1.516679
- Catalog: `openrouter-models-2026-10-21.json`, the coordinator's saved models file (not in the repository; sha256 b17fc211fe65e4347e6808adbb2d35b4d2106aca90e690a81fcc5e66c6b89c9f), looked up 2026-10-22T07:59:47Z
- Registry modules with a live step contract: 2 of 25
- Max tokens: 32000 per call (every model)
- Cells planned: 1; steps run: 1; not authorized by CP-0: 0
- Stopped: no

## Pool

| Model | Eligible | Reason | Requested effort | Effort sent | Reserved USD per attempt (largest) |
| --- | --- | --- | --- | --- | --- |
| openai/gpt-6.1-sol | yes |  | high | high | 1.641444 |

## Steps

| Cell | Case | Step | Model | Seed | Attempt | Status | Class | USD | Issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| probe-00 | probe | source_readiness | openai/gpt-6.1-sol | 1404762132 | d7970902-e97b-48aa-921f-e5171c0ca8f1-source_readiness-1 | rejected | ok | 0.483321 | 1 |

## Cohorts

| Cohort | Attempts | Accepted | Rejected | Pooled | Qualification |
| --- | --- | --- | --- | --- | --- |
| openrouter-pool | 1 | 0 | 1 | yes | not decided here |
