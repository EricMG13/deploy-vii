# Product CLI — implemented surface

Use the committed Python/uv environment (`make setup`). Browser checks additionally
need `uv run --locked playwright install chromium`. Product checks are
`make product-check`; development context tooling remains `make dev-check`.

```sh
uv run --locked deploy-vii plan CP-6 CP-4
uv run --locked deploy-vii preview --run runs/example/run.json --output runs/example/shell-1
uv run --locked deploy-vii prepare --request runs/example/preparation.json --root source-packs/example --output runs/example/pack-1
uv run --locked deploy-vii cp0 --pack runs/example/pack-1 --review runs/example/review.json --output runs/example/cp0-1
```

Each output directory must be new. Preparation reads only named paths within the
selected root; it does not scan for documents or credentials. Snapshot originals
are keyed by SHA-256. The last-written `complete.json` identifies a completed
snapshot; `load_pack` checks its pack identity and every retained original hash.
Editing originals after capture does not change the frozen snapshot. Reprepare
into a new directory for changed evidence; consumer invalidation/runtime retry
tracking is the next execution increment, not implemented by these commands.

A preparation request contains `schema_version: preparation-request/1`, `run`
(the `Run` contract) and `sources`, each with `source_id`, relative `path` and
explicit `media_type`: `text/plain`, `application/pdf`, or
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
Use JSON Schema from the current contracts when authoring inputs:

```sh
uv run --locked python -c 'import json; from deploy_vii.preparation import PreparationRequest; print(json.dumps(PreparationRequest.model_json_schema(), indent=2))'
uv run --locked python -c 'import json; from deploy_vii.readiness import ReadinessReview; print(json.dumps(ReadinessReview.model_json_schema(), indent=2))'
```

`cp0` validates a supplied evidence-grounded review; it does not call a model.
The review binds the prepared pack hash, objective, reporting period, issuer
confirmation, every source assessment, every selected live consumer, gaps and
cited analysis. Source identity/classification comes from located content, not
filenames. Extraction status and original authority are separate. `READY` cannot
omit relevant gaps or source limitations. `CONDITIONAL` identifies a missing
source; analytical upstream execution is checked separately. CP-MODEL/CP-MEMO
and aliases are not live recommendation rows.

Delivery retains candidate/review/accepted artifacts, both views and HTML files,
and a receipt hashing all deliverables. Acceptance is structural validation of a
supplied review, not proof of source sufficiency or analytical quality. Synthetic
cases remain restricted. Blocked accepted views suppress findings and facts;
the candidate retains inspection evidence. All other modules remain unrun.
The receipt keeps analytical, browser and native-host qualification separate;
browser tests write their own evidence without rewriting immutable receipts.

Text preparation retains UTF-8 line locators. PDF preparation retains each page's
text or gap and explicitly requires visual/fidelity review; it performs no OCR.
XLSX preparation preserves raw XML number strings, formulas and stored caches,
sheet/cell locators, hidden state, formats, merged ranges and comments. It never
executes formulas/macros or follows external relationships. Numbers are not Excel
display values and date serials remain unconverted with the workbook epoch named.
Legacy XLS, images and slides are not supported by this milestone. Size limits
bound original/ZIP input, not operating-system memory during PDF decompression.

View bindings: `module_id + table_id + row_id + field` become a `Fact`, selected
with `[data-module-id][data-fact-id]`; Python formats its exact value. CP-0 P3/P5
and T1–T8 render as tagged panels; source IDs bind `[data-source-id]` in Evidence.
The inspector retains source hash, locator, coverage, extraction limitations and
workbook metadata. CP-0 charts are not applicable. Core financial chart/table
parity is still pending with deterministic calculations.
