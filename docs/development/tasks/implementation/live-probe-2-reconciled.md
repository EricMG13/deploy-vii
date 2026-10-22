# Live batch probe-2 (reconciled)

- Checked: 2026-10-21T23:49:46Z; regenerated on every `deploy-vii live reconcile`
- Batch report: live-probe-2.md (written at run time, never rewritten)
- Cap: 10 USD; reserved 0, spent 0.006900855990, remaining 9.993099144010, overrun 0
- Looked up this run: 3; reconciled 3, unresolved 0

## Steps

| Cell | Case | Step | Model | Seed | Attempt | Status | Class | USD | Issues | Cohort |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| probe-00 | probe | source_readiness | openai/gpt-6-luna | 1305688769 | 2d1d9f0f-c9de-41be-b326-6c890a572756-source_readiness-1 | no-response | http_error | 0 | 0 | openrouter-pool |
| probe-01 | probe | source_readiness | openai/gpt-6-luna | 1305688770 | ea0af6cb-f58e-4c3c-b394-937a3702b2a8-source_readiness-1 | no-response | http_error | 0 | 0 | openrouter-pool |
| probe-02 | probe | source_readiness | openai/gpt-6-luna | 1305688771 | f818a0b6-ab0a-412c-b03d-de9e2814294d-source_readiness-1 | no-response | http_error | 0 | 0 | openrouter-pool |
| probe-03 | probe | source_readiness | z-ai/glm-5.3-flash | 1305688777 | d3497b71-cf39-4106-9751-e7a031ae3948-source_readiness-1 | rejected | ok | 0.002417062305 | 17 | openrouter-pool |
| probe-04 | probe | source_readiness | z-ai/glm-5.3-flash | 1305688779 | 3e3a9bbc-c5b3-442d-84fb-cb38e89b9322-source_readiness-1 | rejected | ok | 0.001819983555 | 1 | openrouter-pool |
| probe-05 | probe | source_readiness | z-ai/glm-5.3-flash | 1305688788 | a7bf53ae-3da6-4f65-9786-f6cc44dee8e9-source_readiness-1 | rejected | ok | 0.00266381013 | 1 | openrouter-pool |
| probe-06 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1305688790 | d7caf360-d6d6-4f1c-8e57-af5aa66de00a-source_readiness-1 | no-response | http_error | 0 | 0 | openrouter-pool |
| probe-07 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1305688793 | 61c37274-b5d8-47f0-b53b-4f08467fffb2-source_readiness-1 | no-response | http_error | 0 | 0 | openrouter-pool |
| probe-08 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1305688794 | b8416076-bc7b-48a0-9300-0cb0f82fadf2-source_readiness-1 | no-response | http_error | 0 | 0 | openrouter-pool |

## Reconciliation

| Attempt | Generation | Id source | Held USD | Reconciled USD | Outcome | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| 61c37274-b5d8-47f0-b53b-4f08467fffb2-source_readiness-1 | gen-1792615517-FyjMRTLcVeBphWVoR982 | response.json | 0.2794680 | 0 | reconciled | generation 404; account usage moved 0.006900855, the other attempts' measured costs 0.006900855990 (within 0.000001): the held attempt cost 0 |
| b8416076-bc7b-48a0-9300-0cb0f82fadf2-source_readiness-1 | gen-1792615821-1F3UqeuKW21RjEnBSTVN | response.json | 0.2794680 | 0 | reconciled | generation 404; account usage moved 0.006900855, the other attempts' measured costs 0.006900855990 (within 0.000001): the held attempt cost 0 |
| d7caf360-d6d6-4f1c-8e57-af5aa66de00a-source_readiness-1 | gen-1792615216-IeCvDX2rmXpw9DDxWqjP | response.json | 0.2794680 | 0 | reconciled | generation 404; account usage moved 0.006900855, the other attempts' measured costs 0.006900855990 (within 0.000001): the held attempt cost 0 |
