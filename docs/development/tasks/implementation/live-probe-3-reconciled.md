# Live batch probe-3 (reconciled)

- Checked: 2026-10-22T02:41:41Z; regenerated on every `deploy-vii live reconcile`
- Batch report: live-probe-3.md (written at run time, never rewritten)
- Cap: 5 USD; reserved 0, spent 0.0458498832, remaining 4.9541501168, overrun 0
- Looked up this run: 0; reconciled 0, unresolved 0

## Steps

| Cell | Case | Step | Model | Seed | Attempt | Status | Class | USD | Issues | Cohort |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| probe-00 | probe | source_readiness | openai/gpt-6-luna | 1048690175 | f136b227-3f0a-47b6-89aa-a8ed8f5a4ce4-source_readiness-1 | rejected | ok | 0.02306155 | 4 | openrouter-pool |
| probe-01 | probe | source_readiness | openai/gpt-6-luna | 1048690177 | 8634aa17-a67d-4aa4-a587-a25de14e7343-source_readiness-1 | rejected | ok | 0.00588996 | 7 | openrouter-pool |
| probe-02 | probe | source_readiness | z-ai/glm-5.3-flash | 1048690179 | dccfe8f5-fc21-4374-91dc-da1bdb83a497-source_readiness-1 | accepted | ok | 0.0058930462 | 0 | openrouter-pool |
| probe-02 | probe | source_context | z-ai/glm-5.3-flash | 1048690179 | f0391c45-a82a-4cd1-9d46-4b57fea06d78-source_context-1 | rejected | ok | 0.0052961002 | 5 | openrouter-pool |
| probe-03 | probe | source_readiness | z-ai/glm-5.3-flash | 1048690181 | 76fc5c95-7613-40ce-8d65-428a152f0ccf-source_readiness-1 | rejected | ok | 0.0057092268 | 2 | openrouter-pool |
| probe-04 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1048690185 | f37b8b7e-b887-478f-91b8-8368d630566e-source_readiness-1 | no-response | timeout | 0 | 0 | openrouter-pool |
| probe-05 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1048690189 | 4cb8ee7f-a86a-44b1-b176-5c2b10b8da56-source_readiness-1 | no-response | timeout | 0 | 0 | openrouter-pool |

## Reconciliation

| Attempt | Generation | Id source | Held USD | Reconciled USD | Outcome | Reason |
| --- | --- | --- | --- | --- | --- | --- |
