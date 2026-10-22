# Live batch probe-5b

- Command: probe
- Pool: user-selected (coordinator ruling 22 October 2026)
- Seed: 731169231
- Cap: 3 USD; reserved 0, spent 0.9390855, remaining 2.0609145
- Catalog: `openrouter-models-2026-10-21.json`, the coordinator's saved models file (not in the repository; sha256 b17fc211fe65e4347e6808adbb2d35b4d2106aca90e690a81fcc5e66c6b89c9f), looked up 2026-10-22T03:47:21Z
- Registry modules with a live step contract: 2 of 25
- Max tokens: 32000 per call (every model)
- Cells planned: 2; steps run: 3; not authorized by CP-0: 0
- Stopped: no

## Pool

| Model | Eligible | Reason | Requested effort | Effort sent | Reserved USD per attempt (largest) |
| --- | --- | --- | --- | --- | --- |
| openai/gpt-6.1-sol | yes |  | high | high | 1.646100 |
| x-ai/grok-4.7 | yes |  | xhigh | xhigh | 1.545392 |

## Steps

| Cell | Case | Step | Model | Seed | Attempt | Status | Class | USD | Issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| probe-00 | probe | source_readiness | openai/gpt-6.1-sol | 731169235 | cf6bf65b-e813-44e4-9f87-39b59aeea746-source_readiness-1 | accepted | ok | 0.4822035 | 0 |
| probe-00 | probe | source_context | openai/gpt-6.1-sol | 731169235 | 5ae16ef9-a96e-4b48-93f5-faa623773d19-source_context-1 | no-response | http_error | 0 | 0 |
| probe-01 | probe | source_readiness | x-ai/grok-4.7 | 731169239 | 8c68df3d-fe2b-4292-9ae6-ad4a504b302b-source_readiness-1 | rejected | ok | 0.456882 | 1 |

## Cohorts

| Cohort | Attempts | Accepted | Rejected | Pooled | Qualification |
| --- | --- | --- | --- | --- | --- |
| openrouter-pool | 3 | 1 | 1 | yes | not decided here |
