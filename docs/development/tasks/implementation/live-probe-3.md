# Live batch probe-3

- Command: probe
- Seed: 1048690175
- Cap: 5 USD; reserved 0, spent 0.2581328832, remaining 4.7418671168
- Catalog: `openrouter-models-2026-10-21.json`, the coordinator's saved models file (not in the repository; sha256 b17fc211fe65e4347e6808adbb2d35b4d2106aca90e690a81fcc5e66c6b89c9f), looked up 2026-10-21T23:50:40Z
- Registry modules with a live step contract: 2 of 25
- Cells planned: 6; steps run: 7
- Stopped: no

## Pool

| Model | Eligible | Reason |
| --- | --- | --- |
| openai/gpt-6-luna | yes |  |
| z-ai/glm-5.3-flash | yes |  |
| deepseek/deepseek-v4.1-flash-1017 | yes |  |

## Steps

| Cell | Case | Step | Model | Seed | Attempt | Status | Class | USD | Issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| probe-00 | probe | source_readiness | openai/gpt-6-luna | 1048690175 | f136b227-3f0a-47b6-89aa-a8ed8f5a4ce4-source_readiness-1 | rejected | ok | 0.02306155 | 4 |
| probe-01 | probe | source_readiness | openai/gpt-6-luna | 1048690177 | 8634aa17-a67d-4aa4-a587-a25de14e7343-source_readiness-1 | rejected | ok | 0.00588996 | 7 |
| probe-02 | probe | source_readiness | z-ai/glm-5.3-flash | 1048690179 | dccfe8f5-fc21-4374-91dc-da1bdb83a497-source_readiness-1 | accepted | ok | 0.0058930462 | 0 |
| probe-02 | probe | source_context | z-ai/glm-5.3-flash | 1048690179 | f0391c45-a82a-4cd1-9d46-4b57fea06d78-source_context-1 | rejected | ok | 0.0052961002 | 5 |
| probe-03 | probe | source_readiness | z-ai/glm-5.3-flash | 1048690181 | 76fc5c95-7613-40ce-8d65-428a152f0ccf-source_readiness-1 | rejected | ok | 0.0057092268 | 2 |
| probe-04 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1048690185 | f37b8b7e-b887-478f-91b8-8368d630566e-source_readiness-1 | no-response | timeout | reservation held 0.1061415 | 0 |
| probe-05 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1048690189 | 4cb8ee7f-a86a-44b1-b176-5c2b10b8da56-source_readiness-1 | no-response | timeout | reservation held 0.1061415 | 0 |

reservation held: no measured cost was returned, so the whole reservation counts as spent until `deploy-vii live reconcile` records the provider's charge for that generation.

## Cohorts

| Cohort | Attempts | Accepted | Rejected | Pooled | Qualification |
| --- | --- | --- | --- | --- | --- |
| openrouter-pool | 7 | 1 | 4 | yes | not decided here |
