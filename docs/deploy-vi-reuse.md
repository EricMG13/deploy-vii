# Deploy VI reuse assessment

Reviewed 20 October 2026. Recommendation: selectively reuse deterministic logic,
methodological knowledge and regression cases, and adapt the existing Direction C
report app. Rebuild only the execution boundaries needed for Deploy VII. This is
a source-based shortlist, not a qualification of every file or permission to import
the old project wholesale.

## Evidence boundaries

- Working checkout: `/Users/ericguei/Documents/Deploy VI`, HEAD
  `5c491b715aecdba8cc1d5e5db804928569f95e67`, with modified documents and untracked
  `simple-pathways/` work. Its foundation alone understates what exists elsewhere.
- Locally recorded `origin/main`: `bd71346301b373afa72655916a4c1b42bf4c9823`.
  Inspected Git objects without changing the checkout or fetching the remote.
  This snapshot contains CP-4 and later reporting code, unlike the older
  `16617a0` checkpoint discussed in the restored research.
- The Direction C report app is working-tree material with no commit identity
  in this checkout. Selected files are hashed in the [source record](review-evidence/2026-10-20-sources.json).
  Its historical handoffs report tests; those results were not rerun here.
- Selected implementations, contracts, tests and handoffs were inspected. No
  full security audit, live model run, financial-method qualification or fresh
  browser acceptance was performed. No source code or policies were copied.

Paths below are relative to Deploy VI. **Pinned** means the recorded `origin/main`
commit above; **working** means the locally observed working files.

## Reuse candidates

“Reuse” means preserve the useful algorithm, definition, asset or test with little
semantic change after checking dependencies and rights. All imports still require
Deploy VII tests; existing files are not evidence that the new integration works.

| Candidate and source | Value | Qualification before reuse |
| --- | --- | --- |
| `rbot/scripts/rbotlib/calc/` — pinned; sampled `bond_analytics.py` | Deterministic calculations, explicit conventions and Decimal arithmetic | Review each selected calculator with matching boundary/property fixtures. Preserve assumptions and limitations; do not relabel approximations as exact market pricing. |
| `rbot/scripts/rbotlib/model/` — pinned; sampled `metrics.py` | Period-aware leverage/coverage, typed missing reasons, source/formula lineage | Reuse the necessary dependency slice, not isolated functions stripped of frame/cell semantics. Test period matching, signs, units, denominators and house adjustments. |
| `rbot/modules/*/contract.json` and original `reference/deploy-v-r14/` methodology | Established analytical questions, registers, distinctions and edge cases | Select the intended method explicitly and map coverage. Restore needed analytical depth; old prompt budgets and merged phases do not decide it. |
| Matching pinned calculation/model/parser tests and synthetic fixtures | Existing adversarial examples and expected values | Confirm expected behavior against the selected method; port cases, removing environment coupling. Synthetic inputs stay labelled synthetic. |
| Direction C colours/type/provenance vocabulary in the attachment and working report app | Existing visual identity and familiar report navigation | Match the user's attachment, verify font/logo provenance and include local licensed assets when delivering offline. |

## Adapt candidates

| Candidate and source | Adaptation | Main boundary to verify |
| --- | --- | --- |
| `inventory.py`, `prepare.py` — pinned | Keep source identity, anchored PDF/text/XLSX extraction and visible unreadable states; isolate from old run/state objects | Formula and cached spreadsheet views, hidden sheets, scaling, page/row locators, changed sources and parser failure. |
| `contract.py`, `handoff.py`, `validate.py` — pinned | Retain explicit input/output contracts, tagged tables and citation checks against the new handoff envelope | Prose/checker consistency, duplicate IDs, hostile text, missing/conflicting inputs and real downstream consumers. |
| CP-0/1/1A/2/3/4/5 contracts — pinned | Port analytical responsibilities and dependencies to the new execution host | CP-1A before CP-2; optional inputs when available; CP-4's legal definitions; CP-5's actual evaluation scope. Existing CP-4 is a candidate, not proven complete. |
| `simple-pathways/report-app/` — working | Adapt shell, tokens, navigation, provenance, Model, chart/table twins, print and offline builder to accepted Deploy VII artifacts | Highest-value UI starting point. Replace fixture-specific schema/paths and assumptions; exercise partial, blocked, stale and cumulative module output. |
| `rbot/scripts/rbotlib/report/` — pinned | Reuse relevant assembly/normalization concepts where compatible with Direction C | It has its own state/asset/contracts dependencies. Select one final rendering path; avoid maintaining two competing report models. |
| `scripts/dev_evidence.py` — working | Reuse timing/hash/command-evidence ideas in a small model-test collector | It records local development commands and old phase/budget conventions; add real API usage/provider/attempt/render data instead of assuming it already does so. |
| `docs/development/task-brief-template.md` — working | Keep Inputs/Process/Outputs and a concise result as development ICM | Remove old agent roles, scope restrictions, numerical budgets and review retirement. Follow Deploy VII's current user instructions. |
| State, resume, origin and receipt code — pinned inventory | Borrow only invariants needed for explicit accepted artifacts, invalidation and safe retries | Requires a focused source review before porting. Avoid wholesale transfer of the old qualification/approval lifecycle. |
| 18 October performance review — working document | Turn measured old bottlenecks into hypotheses for new code | Repeated citation parsing, XLSX extraction and qualification are leads; historical timings are not new performance results. |

The working report app contains concrete portability issues to address: for example,
`report-app/tests/test_shell.py` hardcodes a fixture pack under
`/tmp/rbot-report-design-20261020/`. Its builder expects companion fonts and brand
assets. `simple-pathways/pathways/credit.py` imports `rbotlib` preparation/model
code: the small wrapper is not a self-contained replacement for those dependencies.

## Leave behind

| Item | Reason |
| --- | --- |
| Deploy VI AGENTS/CLAUDE policies, agent profiles, hooks and CI settings | A separate project's operating rules. Do not inherit its role assignments, permissions, line caps or retired-review decisions. |
| Old approvals, installation qualification, evidence receipts and completed-run statuses | Bound to different code, sources and host. They cannot qualify Deploy VII. |
| Whole historical plans, duplicate review/handoff chains and every backlog module | Keep relevant references; do not import a second active roadmap or build unused features. |
| Old report directions A/B and the unrelated `design/mockups/report-c-period-spine.*` appearance | A filename containing “C” is not the attached Workbench direction. They are optional implementation references only. |
| Illustrative issuer figures, hardcoded verdicts, fixture-only conclusions and sample completion counts | Useful test data when labelled; never real results or defaults for unfinished modules. |
| One long shared analytical conversation and serial execution as the sole dependency definition | Explicit input identities and required/optional dependencies suit the proposed Module architecture. |
| Unmeasured framework layers, blanket prompt cuts and speculative parallelism | Carry forward only demonstrated needs, preserving method and correctness. |
| Private packs, raw historical telemetry, caches, virtual environments and build outputs | Reference or regenerate deliberately; do not sweep them into the new repository. |

## Suggested adaptation order

1. During the first implementation increment, establish the Direction C shell
   and minimal artifact-to-view contract with honest unrun states.
2. Build CP-0/source intake and the random-model test evidence collector; show
   its real readiness output in the shell immediately.
3. Port the necessary CP-1/Model calculations and regression cases, then CP-1A
   context and subsequent analytical Modules in dependency order.
4. Add each Module's field bindings and rendering checks as it is tested. Use
   the same collector for quality, repair, cost and latency evidence.
5. Revisit state machinery or frameworks only when a tested requirement needs
   them; apply the existing bounded maintenance sweep design.

This sequence is a recommendation for future implementation, not work performed
by this review. See [methodology](methodology-adaptation.md),
[testing](testing-and-telemetry.md), [frontend](frontend-direction-c.md) and
[development ICM](development-context.md).
