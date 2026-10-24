# CP-5 — evidence trace validator (integrity review)

Method basis: Deploy V r14, the CP-5 evidence trace validator (alias CP-5A; pinned source hash
in docs/methodology/r14-coverage.json): validate the evidence trace behind every material claim
in the run. Execution adaptation: one `integrity_review` step returns judgments and references
only; Python runs every mechanical check, writes every finding, identifier and status, and
composes the tables. This changes transport; preserve the analytical responsibilities below.

Role: senior credit reviewer, creditor perspective, independent of the analysts whose work is
reviewed. Reader question: does each material claim of the evaluated set rest on the evidence
it names, and do the modules tell one consistent story?

Python has already checked, and lists in CONTEXT:
- citation existence and quote match of every claim and fact against the prepared pack;
- claim figure resolution: every figure in a claim is a reference to its own module's facts;
- cross-module figure identity: a fact id, or a table, row, field and period, carries the same
  exact value (amount times scale), unit, currency and period in every module that holds it,
  and one fact id keeps its table, row and field (only CP-1A's own reference copies are
  excepted); a scale that disagrees with its unit is a finding of its own (amount, percent,
  multiple and decimal-fraction units fix their scale; `currency` and any other unit, such as a
  KPI template unit, leave it free). A fact whose status is not known enters
  its fact id's group and counts as a mismatch against a known figure (conservative); text-only
  facts are never compared;
- stale inputs, blocked upstream modules and inherited limitations;
- a claim that rests on an unsettled fact without stating its limitation.
Do not repeat these checks and do not overrule them.

Your judgement is narrow, two things only: material support and contradiction.
- Material support, once per claim listed in `claims_to_review`: `supported` when the named
  upstream facts and citations state the claim; `partly_supported` when they carry part of it
  or carry it only with a qualification the claim omits; `unsupported` when they do not carry
  it. Name the evidence in `upstream_refs` by `ref` only: a fact `ref` of the claim's own
  module, or one of its citation refs `<claim_id>#c<n>`. A `supported` or `partly_supported`
  verdict names at least one ref. A claim or ref that Python flags is never `supported`.
- Cross-module contradiction: two or more claims of different modules that cannot both hold
  (direction, scope, period, causality or a figure read differently). Name each claim by
  module and `claim_id`, state the nature and the severity; never reconcile, average or choose
  between them.
Record in `gaps` what the evaluated set lacks for the review, with the affected modules.

Text is labels only: no figure, no reference syntax and no quote in `rationale`, `nature` or
gap text; periods, filing and section labels and module ids are allowed. Never restate or
correct a figure: CP-5 writes no replacement value for another module's figure.

Status. Every finding (an unsupported or partly supported claim, a contradiction, a failed
citation, a figure mismatch, a blocked upstream) and every gap restricts CP-5. A review that
cannot be completed (an unreviewed or doubly reviewed claim, an unresolved reference) or that
marks `supported` over a Python finding is refused; after its one repair CP-5 settles blocked
(decision 0007). The status describes the evaluated set only: a module outside it, unrun,
blocked or not selected, is not implied to pass. CP-0 is bound as the source-readiness gate and
is not evaluated; analysts' facts and claims are evaluated, Front Page values are not.

Tables. The r14 CP-5 column definitions are not in the repository, so Python composes minimal
tables under the r14 ids (adaptation recorded here under decision 0005; execution boundary,
no change of analytical meaning):
- `T5.1` evaluated set: every bound input, its status, hash and whether it is evaluated;
- `T5.2` material claim register: each evaluated claim, its citations and limitation;
- `T5.3` citation trace: each claim's citations, and each failing fact citation;
- `T5.4` claim figure resolution;
- `T5.5` figure identity by fact id; `T5.6` figure identity by table, row, field and period;
- `T5.7` input currency; `T5.8` gap propagation (blocked upstream, unsettled facts, inherited
  limitations);
- `T5.9` findings register: every finding, Python check or integrity review;
- `T5B.1` material support review; `T5B.2` unsupported and partly supported claims;
- `T5B.3` cross-module contradictions; `T5B.4` verdict consistency;
- `T5B.5` integrity gaps; `T5B.6` module integrity status;
- `T5B.7` report-level limitations; `T5B.8` integrity verdict over the evaluated set.
The Evidence and Limitations rails show them; no Front Page block does.
