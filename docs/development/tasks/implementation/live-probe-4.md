# Live batch probe-4

- Command: probe
- Pool: user-selected (coordinator ruling 22 October 2026)
- Seed: 1757377039
- Cap: 10 USD; reserved 0, spent 1.37794208064, remaining 8.62205791936
- Catalog: `openrouter-models-2026-10-21.json`, the coordinator's saved models file (not in the repository; sha256 b17fc211fe65e4347e6808adbb2d35b4d2106aca90e690a81fcc5e66c6b89c9f), looked up 2026-10-22T01:10:39Z
- Registry modules with a live step contract: 2 of 25
- Cells planned: 8; steps run: 8
- Stopped: aborted: ValueError

## Pool

| Model | Eligible | Reason | Requested effort | Effort sent | Reserved USD per attempt (largest) |
| --- | --- | --- | --- | --- | --- |
| deepseek/deepseek-v4.1-flash-1017 | yes |  | max | max | 0.1061607 |
| x-ai/grok-4.7 | yes |  | xhigh | xhigh | 1.351452 |
| xiaomi/mimo-v2.6-pro | yes |  | high (default) | none; reasoning enabled (catalog lists no reasoning_effort; provider default reasoning depth) | 0.140011275 |
| openai/gpt-6.1-sol | yes |  | high | high | 1.399456 |

## Steps

| Cell | Case | Step | Model | Seed | Attempt | Status | Class | USD | Issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| probe-00 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1757377040 | c1540d12-68a8-4e05-a1b6-9b21481ce55a-source_readiness-1 | no-response | http_error | 0 | 0 |
| probe-01 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1757377042 | 9d68b734-2da4-4b85-9335-d09b70324b71-source_readiness-1 | rejected | ok | 0 | 1 |
| probe-02 | probe | source_readiness | x-ai/grok-4.7 | 1757377046 | 7812cd5f-8321-4066-ad5f-91ea929a22de-source_readiness-1 | rejected | ok | 0.432076 | 4 |
| probe-03 | probe | source_readiness | x-ai/grok-4.7 | 1757377050 | 17a71fce-6b1a-44de-9ced-26f146d8ac89-source_readiness-1 | rejected | ok | 0.27259 | 2 |
| probe-04 | probe | source_readiness | xiaomi/mimo-v2.6-pro | 1757377053 | f33915f2-6cd5-46ac-940b-c050389570dd-source_readiness-1 | rejected | truncated | 0.07520652 | 1 |
| probe-05 | probe | source_readiness | xiaomi/mimo-v2.6-pro | 1757377055 | 13d5a6bb-d5ea-407e-bac7-ab0bb67dcc9a-source_readiness-1 | rejected | truncated | 0.01306196064 | 1 |
| probe-06 | probe | source_readiness | openai/gpt-6.1-sol | 1757377058 | 9594d016-b8b7-432c-8b50-e7a9f7fbb6bb-source_readiness-1 | rejected | ok | 0.478201 | 3 |
| probe-07 | probe | source_readiness | openai/gpt-6.1-sol | 1757377060 | 944e569a-f521-446b-8784-cfc79abea0d7-source_readiness-1 | accepted | ok | 0.1068066 | 0 |

## Cohorts

| Cohort | Attempts | Accepted | Rejected | Pooled | Qualification |
| --- | --- | --- | --- | --- | --- |
| openrouter-pool | 8 | 1 | 6 | yes | not decided here |
