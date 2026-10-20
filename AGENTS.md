# Deploy VII

This is a standalone project. Work in this folder.

Current authorization: review the research and implement the development
environment and project settings. Decision 0002 records the selected setup;
docs/development/CONTEXT.md is the development entry point. Product implementation
and live model tests are subsequent increments. Historical snapshots and attached
documents are reference material, not instructions or adopted settings.
Do not inherit another project's policies, code, agent profiles or hooks.

Development conventions:

- Use Python 3.13.15 and uv 0.12.5 with the committed lock. Run `make setup`
  once per checkout, `make check` for hygiene, `make secrets` before publication
  and `make audit` for dependency changes. Activate product checks with real code.
- Keep task context in docs/development/tasks; ICM is for development only.
- Keep credentials, issuer packs and raw run/telemetry artifacts out of Git.
- One owner per worktree. Workers return local commits; the coordinator owns
  publication and integration. Delegation requires explicit task or skill scope.
- Worker routes are explicit choices; do not override the current coordinator
  model or silently switch providers. Global host plugins are separate state.
- Inspect the full candidate diff. There is no inherited hard line-count cap.

User requirements for product increments:

- Model-assisted tests randomly select an eligible Luna, GLM 5.3 Flash or latest
  DeepSeek model at appropriate high/xhigh effort; retain outputs, metrics and
  telemetry under docs/testing-and-telemetry.md.
- Preserve Direction C Workbench and test each completed Module's output in its
  relevant HTML fields under docs/frontend-direction-c.md.
- Preserve analytical meaning while adapting execution boundaries. Python owns
  arithmetic; models supply evidence-grounded analysis. Follow the reuse review
  before selecting any Deploy VI code.

After code changes run confidence-review. After non-trivial code changes also
run rewrite-tournament in no-argument post-edit mode on changed functions.
Skip the latter for trivial edits, docs/config, test-only and generated files.
