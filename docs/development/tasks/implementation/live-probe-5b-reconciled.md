# Live batch probe-5b (reconciled)

- Checked: 2026-10-22T03:55:29Z; regenerated on every `deploy-vii live reconcile`
- Batch report: live-probe-5b.md (written at run time, never rewritten)
- Cap: 3 USD; reserved 0, spent 0.9390855, remaining 2.0609145, overrun 0
- Looked up this run: 0; reconciled 0, unresolved 0

## Steps

| Cell | Case | Step | Model | Seed | Attempt | Status | Class | USD | Issues | Cohort |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| probe-00 | probe | source_readiness | openai/gpt-6.1-sol | 731169235 | cf6bf65b-e813-44e4-9f87-39b59aeea746-source_readiness-1 | accepted | ok | 0.4822035 | 0 | openrouter-pool |
| probe-00 | probe | source_context | openai/gpt-6.1-sol | 731169235 | 5ae16ef9-a96e-4b48-93f5-faa623773d19-source_context-1 | no-response | http_error | 0 | 0 | openrouter-pool |
| probe-01 | probe | source_readiness | x-ai/grok-4.7 | 731169239 | 8c68df3d-fe2b-4292-9ae6-ad4a504b302b-source_readiness-1 | rejected | ok | 0.456882 | 1 | openrouter-pool |

## Reconciliation

| Attempt | Generation | Id source | Held USD | Reconciled USD | Outcome | Reason |
| --- | --- | --- | --- | --- | --- | --- |
