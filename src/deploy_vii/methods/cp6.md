# CP-6 — investment committee debate and challenge

Method basis: Deploy V r14, the CP-6 IC debate and challenge module (pinned source hash in
docs/methodology/r14-coverage.json). Execution adaptation: one `committee_challenge` step returns
judgments over the settled upstream heads; Python composes every table, assigns every
identifier, spells every figure, maps the call band and sets the status. This changes
transport; preserve the analytical responsibilities below.

Adaptation record (decision 0005): the r14 CP-6 SKILL.md is not in this repository, so neither
its table definitions nor its columns are available. Python composes five minimal tables from
the contract rows below under r14 CP-6 ids: `T6A.4` (action bias), `T6E.4` (committee
challenges), `T6E.6` (recovery view), `T6E.7` (committee risks) and `T6E.11` (gaps ledger).
Which r14 table each id names is an assumption recorded here, not taken from r14. The other
required CP-6 tables are not composed; the call band wiring and the final integrity check at
report assembly are separate changes.

Role: investment committee chair, creditor perspective. Test CP-2's fundamental view against
CP-3's relative value and CP-5's integrity review, then state the committee's action bias.
Reader question: having heard the strongest case against the thesis, what is the committee's
action bias on this issuer, how confident is it, and what would change it?

Evidence. CP-6 reads the settled heads of CP-1, CP-2, CP-3 and CP-5 (CONTEXT lists each head's
claims, limitations and status) and quotes no pack source. Cite rows only by listing their refs,
exactly as CONTEXT writes them: CP-2 rows in `cp2_refs` (under `cp2_rows`), CP-3 rows in
`cp3_refs` (under `cp3_rows`), CP-5 rows in `cp5_refs` (under `cp5_rows`; a CP-5 finding may be
named by its CP-5-FINDING-NNN id); cite, never restate them. Covenant, legal and recovery
evidence reaches CP-6 only through CP-5's findings and limitations: CP-6 binds no CP-4 head.

Challenge discipline. Every `thesis_challenges` row names the CP-2 row it challenges in
`thesis_ref`: a `cp2_rows` ref whose challengeable is true (the thesis, a strength, a weakness or
a key finding), each at most once. State the strongest counter-case, the evidence for and
against the CP-2 point, and what would change the committee's view. Every row cites at least one
ref in its basis, or a CP-1 figure in its text.

Recommendation boundary. CP-6 is the only module that states a final recommendation. It may
state an action bias (Overweight, Neutral, Underweight or Insufficient Information) on the
issuer's credit, with its rationale, the conditions that would move it and a confidence (High,
Medium, Low or Insufficient Information). The action bias and the confidence are Insufficient
Information together, and then the limitation says why. A recovery conclusion is permitted
only on CP-4 evidence CP-5 carries.

What to return:
- `recommendation`: the action bias, rationale, conditions, confidence, limitation and basis.
- `thesis_challenges`: one row per challenged CP-2 row, as above.
- `recovery_view`: each recovery view with its subject, view, confidence, limitation and
  basis. Without a CP-5 finding or limitation carrying CP-4 content (listed under
  `cp5_cp4_rows`; never a blocked CP-4, an inherited limitation or a gap row), a recovery view
  is Insufficient Information and states its limitation.
- `risks`: each risk to the action bias with its mechanic, implication, severity and basis.
- `gaps`: what the committee lacks, why it matters, what it affects, its severity and action.

The CP-5 rule. CP-6 runs only after CP-5's handoff is Passed or Restricted; a blocked required
upstream refuses the step. A restricted CP-5, unsupported or partly supported claims and
contradictions keep the confidence below High (so no High Overweight or Underweight) and
Python records the limitation. A recommendation that is not Insufficient Information is
supported by at least one CP-2 or CP-3 row that bears a claim (marked claim under `cp2_rows`
and `cp3_rows`: the credit assessment, a key finding, the preference, an instrument's market
observation) and that CP-5 does not flag (`cp5_flagged_claims`), or by a CP-1 figure in its
rationale or conditions: a recommendation resting only on flagged claims is refused. Gap and
limitation rows support nothing; cite them only for a limitation.

Gap propagation. Any blocked module up the input chain (listed under `blocked_ancestors` and
`confidence_caps`) keeps the confidence below High and is an own limitation; the run is never
halted by it. Without observed or indicative market evidence in CP-3, or with CP-3's preference
Insufficient Information (listed under `insufficient_information`), the action bias is
Insufficient Information. CP-1A that the run does not select is shown as "not in this run" and
limits nothing; a selected one is never unrun or stale here, since CP-6 does not start until it
settles, so blocked is the only missing state. Python records the limitations and the status;
do not restate them as findings.

Prohibited: no ranking against external peers (CP-1C), no buy, sell or switch phrase, and no
trade terms: never name a buy or sell price, a target or entry level or a position size. An
overweight or underweight bias and a recommendation are this module's output.

Numbers: Python owns every figure and the call band mapping. Write labels only; a figure appears
only as a `{ref|unit}` reference to a fact listed under `cp1_facts` in CONTEXT. Never write a
bare number, a `[ref]` chip, a table id or a row ref in a text field.

Status (decision 0007): own limitations restrict CP-6; a blocked ancestor restricts it with
the inherited "Upstream ... blocked" wording; a failed repair leaves it blocked.

User decision (24 October 2026): the action bias keeps its four values (Overweight, Neutral,
Underweight, Insufficient Information), and the call band's confidence meter is adopted as
Python maps it (`call_scale`): Insufficient Information fills one step of five, Low two,
Medium three and High all five. The differential test
`test_the_call_scale_is_total_monotone_and_matches_the_reference` holds `CALL_SCALE` to a
hand-written reference table. The design-system spelling of the action-bias fact on the page
is still open for M10, in decision 0004 terms.
