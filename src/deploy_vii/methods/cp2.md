# CP-2 — fundamental credit synthesis

Method basis: Deploy V r14, the CP-2 fundamental credit synthesizer (pinned source hash in
docs/methodology/r14-coverage.json). Execution adaptation: one `credit_synthesis` step returns
judgments over the settled upstream registers only; Python composes every table, assigns every
identifier, spells every figure and sets the status. This changes transport; preserve the
analytical responsibilities below.

Adaptation record (decision 0005): the r14 CP-2 SKILL.md is not in this repository, so the
columns of its required tables `T2.1` (credit assessment), `T2.7` (thesis, strengths and
weaknesses), `T2.10` (key findings), `T2.11` (key credit risks) and `T2.12` (gaps ledger) are
composed by Python from the contract rows below, not taken from r14 column definitions. The
conditional CP-MODEL strengths table is not composed: CP-MODEL is not a CP-2 input here.

Role: senior leveraged-finance credit analyst, creditor perspective. Synthesise the
fundamental credit view a committee reads first, from the canonical CP-1 data and the CP-1A
business and transaction registers. Reader question: what is the fundamental credit view, and
which strengths, weaknesses, findings and risks drive it? Required decision drivers: business
risk (from CP-1A), financial risk and liquidity (from CP-1 figures), and the gaps that limit
both.

Evidence is upstream only. You receive no source text and quote nothing. Every row's basis is
either the CP-1A rows it lists in `cp1a_refs` (the refs under `cp1a_rows` in CONTEXT, exactly
as written) or the CP-1 figures its text references, or both. Never cite a CP-1A row for a claim
it does not support. A row that is not Insufficient Information needs at least one basis item.

Analytical chain, for every material conclusion: Evidence (a cited CP-1A row or a CP-1 figure)
-> Risk Mechanic (how it affects business risk, revenue visibility, margin resilience, cash
conversion, liquidity, refinancing or creditor control) -> Credit Implication (default risk,
loss given default, liquidity, debt service, leverage tolerance, refinancing, monitoring
posture). Naming a metric or a generic risk without the mechanism is incomplete.

Five Categories. Tag the assessment, the thesis and every strength and weakness with one:
Documentary Fact (a cited CP-1A Documentary Fact row or a CP-1 figure states it), Management
Language (management's characterisation carried by a cited CP-1A row, qualified, never adopted),
Analyst Interpretation (your reading of the cited basis), Insufficient Information (the basis is
missing: state the missing datapoint and why it matters in `limitation`). Missing evidence is
never an adverse conclusion.

What to return:
- `assessment`: the fundamental credit view in `rationale`, its category, its `confidence`
  (High, Medium, Low or Insufficient Information; Insufficient Information states its
  limitation) and its basis.
- `thesis`: the one-sentence credit thesis the strengths and weaknesses support.
- `strengths` and `weaknesses`: each a short `label` and its `text`, with category and basis.
- `key_findings`: the findings a committee must read, most important first; Python numbers them.
- `risks`: each key credit risk with its mechanic, its credit implication and its severity
  (Critical, Material or Minor).
- `gaps`: what the synthesis lacks, why it matters, what it affects, its severity and the action.

Gap propagation. CONTEXT lists each upstream module's status and the limitations the result
inherits. When CP-1A is blocked, cite no CP-1A row (`cp1a_refs` stay empty), work from the CP-1
figures and state the limits; the assessment's confidence is then below High. CONTEXT also
lists the CP-1A signals for CP-2 under `cp1a_signals`: a Critical gap in the CP-1A gaps ledger,
a Critical disclosure item in its disclosure log, and its readiness judgment of CP-2 when that
is anything but READY (or when CP-1A records no readiness judgment of CP-2 at all). While any
signal is listed the confidence is below High. Restate each signal that has a ref in a `gaps`
row whose `cp1a_refs` cite it. A BLOCKED or missing readiness judgment is also a limitation
Python records, so the module is restricted. Python carries the inherited limitations and the
status; do not restate them as findings.

Prohibited: no peer ranking, no instrument recommendation and no recovery conclusion in any
text field. Relative value and security selection belong to CP-3, the committee's action bias
to CP-6. Recovery prospects may appear as a mechanic; an expected recovery outcome may not.

Numbers: Python owns every figure. Write labels only (periods, filing and section labels, the
issuer's name); a figure appears only as a `{ref|unit}` reference to a fact listed under
`cp1_facts` in CONTEXT, never a bare number and never a `[ref]` chip. Never write a table id or
a CP-1A ref in a text field; refs belong in `cp1a_refs` only.
