# CP-4 — legal covenant interpreter

Method basis: Deploy V r14, the CP-4 legal covenant interpreter (aliases CP-4A, CP-4B, CP-4D;
pinned source hash in docs/methodology/r14-coverage.json). Purpose: interpret the legal and
covenant package and what it actually permits. CP-4C (fulcrum and recovery) is out of scope.
Execution adaptation: one `legal_covenants` step returns judgments and verbatim quotes; Python
checks every quote and threshold, computes every headroom from CP-1 figures, assigns every
identifier, composes every table and renders. This changes transport; preserve the analytical
responsibilities below.

Role: senior leveraged-finance legal and credit analyst, creditor perspective. Reader question:
which provisions protect creditors, what do the documents permit the issuer to do, and how
close is the issuer to each test?

Sources. Cite only the sources CONTEXT lists under `legal_sources` (CP-0 classes them executed
or filed); `other_sources` (management, sponsor, third-party or unknown material) are never
cited. Quote the governing text verbatim. A document row registers one governing source: its
family (indenture, credit agreement, supplemental indenture...), governing entity, date and
amendments, quoting that source only.

Covenants. One row per covenant or test: its name, kind (maintenance, incurrence, negative,
other), the clause it lives in, its defined terms (`definition_text`: what the definition of
EBITDA, debt or the tested ratio adds back or excludes), the test formula in words, the period
it is tested over and the facilities it governs (`facility_ids` from CONTEXT `facilities` only).
Every covenant names its governing document (`document_id`, a `documents` row) and quotes it.
- Threshold: `threshold_text` is copied from one of the row's quotes and holds the one
  threshold tested (a ratio written N to one, a multiple written with x or times, or a
  percentage); `threshold_unit` is multiple or percent for a ratio or percentage, other for any
  other limit (an amount, a grower basket), not stated when the documents state none.
  `threshold_value` is the number exactly as the quote writes it (the N of a ratio to one, the
  number before a percent sign), null for other and not stated; Python reads the number out of
  the quote and rejects a value that differs. `comparison` is how the tested metric must stand
  against the threshold (`<=` a maximum, `>=` a minimum; strict forms where the text is strict).
- Metric: `metric_ref` names the CP-1 figure from CONTEXT `cp1_facts` that the test compares,
  or null. `metric_basis` says whether the covenant's definition is the one CP-1 uses for that
  figure (Same definition), differs (add-backs, pro forma adjustments, excluded debt), or cannot
  be told from the sources (Not determinable). With no `metric_ref` it is Not determinable.

Capacity: each basket or permission (debt, liens, restricted payments, investments, asset
sales), what it permits and its conditions, quoted. Red flags: each provision weak for
creditors (portability, uncapped add-backs, drop-down or uptier capacity, weak asset-sale
sweeps), its mechanic and implication, with a severity. Lender protection: one rating (Strong,
Adequate, Weak or Insufficient Information) with its rationale and the provisions it rests on;
Insufficient Information states its limitation. Gaps: every document or term the analysis
needs and the pack lacks.

Numbers and status are Python's. Write labels only (section, filing and period labels); a
CP-1 figure appears only as a `{ref|unit}` reference from `cp1_facts`, a threshold only inside
its quote. Never state compliance, a breach or an amount of headroom or cushion in any text:
Python computes headroom as the room between the CP-1 metric and the parsed threshold on the
permitted side, its share of the threshold, and whether the metric is within the threshold.
Unknown headroom or capacity is not zero: where CP-1 is blocked, the threshold is not stated or
not a ratio, no metric is matched or the definitions differ, Python writes "Not calculable" with
the reason. Basket capacity amounts are not computed in this version and are shown unsettled.

Prohibited: no instrument recommendation and no recovery conclusion (CP-4C and CP-6 own them);
recovery prospects may appear as a mechanic, an expected recovery outcome may not.

## Tables (r14 ids; Deploy VII placement)

The r14 CP-4 SKILL.md and its column definitions are not in this repository, so each id below
holds a minimal table Python composes from the submission rows and the bound inputs (task 8.2,
coordinator ruling 4). The titles and columns are Deploy VII's assignment, not r14's layout,
and are re-mapped when the SKILL.md is pinned.

| Id | Table | From |
| --- | --- | --- |
| T4.2 | Document register | documents, CP-0 authority |
| T4.3 | Covenant register | covenants |
| T4.9 | Covenant tests and headroom | covenants, CP-1 metric, Python headroom |
| T4.10 | Capacity and baskets | capacity (amount unsettled) |
| T4.11 | Red flags | red_flags |
| T4.12 | CP-4 gaps ledger | gaps |
| T4.13 | Lender protection score | protection_score |
| T4C.2 / T4C.3 / T4C.4 / T4C.5 | Maintenance / incurrence / negative / other covenants | covenants by kind |
| T4C.6 | Covenant definitions | covenants |
| T4C.7 | Threshold check | quoted threshold, stated and parsed value |
| T4C.8 | CP-1 metric binding | metric, period, definition basis, unit |
| T4C.9 | Headroom calculability | Python reason |
| T4C.11 | Covenant-to-facility map | covenants, CP-1 T4.18 |
| T4C.12 | Facility coverage | CP-1 T4.18, covenants |
| T4D.1 | Pack legal source eligibility | pack, CP-0 authority |
| T4D.2 / T4D.3 | Governing entities / dates and amendments | documents |
| T4D.4 | Document quotations | documents' citations |
| T4D.5 | Document limitations | documents |
| T4D.6 / T4D.7 | Capacity conditions / red flag implications | capacity / red_flags |
| T4D.8 | Covenants by governing document | covenants |
| T4F.1 | CP-4 input status | bound inputs |
| T4F.2 | CP-1 figures referenced | CP-1 facts copied value for value |
| T4F.3 | Headroom calculation trace | Python operands and result |
| T4F.4 | Protection score basis | protection_score |
| T4F.5 | Inherited CP-1 gaps | CP-1 limitations |
| T4F.6 | CP-4 source trace | every citation |

## Adaptation record (decision 0005)

- Transport: one model step returns a thin submission; Python composes the 31 tables, ids,
  status and limitations (MC-1, MC-6). Single settling step, attempt-level repair only.
- Thresholds: the model supplies the quoted threshold text, a stated value and a comparison;
  Python parses the number from the quote and rejects a mismatch (ruling 2). Only ratio and
  percentage thresholds are parsed; any other limit is "not calculable". A ratio to anything
  but one is not read (Python never asks the model to divide).
- Direction (fix round 1): the comparison is checked against the threshold's own quote only
  cheaply. A maximum (`<=`, `<`) is rejected when the quote names only a floor (not less than,
  at least, minimum), a minimum (`>=`, `>`) when it names only a cap (not exceed, not to exceed,
  not more than, maximum, shall not be greater). A quote naming neither (the common "shall not
  permit ... to exceed") or both is accepted: there the direction is the model's judgement, a
  residual risk a wrong sign would carry into the headroom.
- Headroom: Python arithmetic over the parsed threshold and a CP-1 figure the model matched and
  judged the same definition; a definition the model judges different or not determinable is
  not compared. A strict test does not hold at the threshold. A percentage test's headroom is
  stated in percentage points (unit `pp`, the room between two percentages times one hundred);
  its share divides the room by the threshold's absolute value and is a percent; a zero
  threshold has no share. The calculation trace (T4F.3) keeps the operands' own units (decimal
  fractions for percentages).
- Degradation: the `CP-1 -> CP-4` edge is `restricted` (decision 0007): a blocked CP-1 is bound
  with status blocked, formulas are still extracted, every headroom and capacity is "not
  calculable", and the journal settles CP-4 `restricted` with the inherited limitation.
- Sources: only executed and filed sources are cited, whole documents as the pack holds them
  (ruling 1). CP-1D is not read in M8 (ruling 5).
- Compliance and headroom language is reserved to Python's cells and refused in model text (a
  phrase guard, not a semantic review).
- Basket capacity amounts are not computed in M8: shown unsettled with one module limitation.
