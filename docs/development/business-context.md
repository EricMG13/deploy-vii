# CP-1A business and transaction context (task 7.2)

CP-1A (alias CP-2C) answers r14's reader question: what the issuer does, who owns and controls
it, and what transaction or event is in front of the reader, translated into credit mechanics.
In Deploy VII it is one live step, `business_context`, after CP-0 (decision 0008 MC-1: a Python
skeleton; the model supplies judgments and verbatim quotes only). Code:
`src/deploy_vii/business_context.py`; prompt text: `src/deploy_vii/methods/cp1a.md` and
`live/prompts.py` `STEP_CONTRACTS["business_context"]`; bindings: `bindings/cp1a.py`.

## The submission (`BusinessContextSubmission`)

Every field is required; an optional value is nullable (strict-schema rules, `live/schema.py`).
`company` and `consumers` carry `minItems: 1`. Lists: `sources` (each prepared source once:
class, quality, period, entity covered, data supplied, use, limitation), `company` (one row per
aspect: business description, country, sector), `business_lines`, `owners`,
`operating_drivers` (measure null exactly when the driver is Not disclosed), `transactions`,
`events`, `governance_and_sponsor` (T2D.3 topics and T2D.4 behaviour flags in one list, `kind`
says which; a flag states its behaviour type, amount/funding source and legal-capacity link, a
topic leaves them null), `capital_allocation` (T2D.5), `acquisitions` (T2D.6),
`disclosure_items` (T2D.7, `available` is r14's Yes / No / Partial / Insufficient Information),
`credit_translations` (theme, evidence, risk mechanic, credit implication, confidence, the
conflict ids that counter it), `conflicts` (an id and at least two citations; logged, never
reconciled), `gaps`, `consumers` (exactly the CONTEXT list). Fact rows carry the Five
Categories as a closed enum (`Documentary Fact`, `Management Language`, `Analyst
Interpretation`, `Insufficient Information`); evidence quality, confidence, severity,
statuses and directions are closed enums too. Citations are `{source_id, locator, quote}`
under the CP-0 rules; Python binds the pack's source hash.

Additions beyond the plan's field list, each needed to fill an r14 column without inventing a
value: `sources` (source_classification, T2D.1), the category on fact rows, the owner's
evidence quality, credit mechanic and implication (T2D.2), the acquisition period, risk
mechanic and implication (T2D.6), the gap's why-it-matters (T2D.11), the consumer's handoff
item and why-it-matters (T2D.10), the translation theme and countervailing conflict ids
(T2D.9), the conflict id, and the governance row's dimension (T2D.8).

## Validator (`validate_business_context`)

Issues are returned, never raised, in a stable order; the journal sends them back as the REPAIR
block. Rules: every prepared source assessed exactly once (an unavailable one is Insufficient;
an assessment cites only its own source); citations bind to ready sources and pass the CP-0
quote check, with the row path prefixed; every text field is run text (`prose.issues`: digits
only in labels and the issuer's name, figures only as `{ref|unit}` to a CP-1 fact the CONTEXT
block offered, no `[ref]` chips) and is not blank; the coverage rule (`absence_issues`); the
category rules (a non-Insufficient row cites located evidence, an Insufficient row states its
limitation); a credit translation above Insufficient cites its evidence; a conflict cites two
spans; an available disclosure cites where; company aspects exactly once; conflict ids unique,
well formed and the only ones a translation may name; at least one fully evidenced credit
translation (`cp1a.credit_translation_has_evidenced_row`); consumers unique and exactly the
CONTEXT list (`cp1a.downstream_modules_unique`); no prohibited conclusion (`PROHIBITED`: peer
ranking, instrument recommendation, recovery conclusion, a closed phrase list matched on word
boundaries; recovery as a credit mechanic is allowed). After composition,
`register_rule_issues` checks the four `cp1a.*` rules on the registers themselves.

## Registers (Python)

`business_context(pack, submission, cp1_facts)` composes the 22 r14 registers with r14's table
ids and column labels plus the conditional `cp1a.cp_model_snapshot_fields`, and a
`cp1_references` table copying each CP-1 fact the text references (with its citations). A fact
row's main cell carries its category tag (` [Management Language]` and so on); a Source Trace
is Python's `source_id locator` list. An empty register is one row of unsettled cells:
`missing` (a gap and a module limitation) or, for the conflict log and the two gap ledgers,
`not_applicable` ("none logged"). Python-owned values: the issuer name (run identity), the
revenue-mix status (from the category), the gaps-ledger status (`Open`), the conflict
resolution (`Logged, not reconciled`), T2D.4 flag ids (`CP-2C-FLAG-001`), T2D.10 tags
(`CP-2C-HANDOFF-<module>`) and destinations, T2D.11 gap ids (`CP-1A-GAP-001`) and consequence
for confidence (Critical High, Material Medium, Minor Low), and the snapshot fields (READY only
where a located row supplies them, else GAP with unsettled value and source cells).
Claims: one per credit translation, `<evidence> Risk mechanic: ... Credit implication: ...`,
as run text. Limitations: each Insufficient row's limitation, each gap (`Gap (<severity>):`),
each empty `missing` register, and an Insufficient risk level.

### T2D.8: governance and sponsor score (derived, not asked of the model)

Rows inform a dimension when they name one of r14's nine dimensions and nothing about them is
Insufficient (direction, category, evidence quality). Per dimension (`dimension_score`): all
Supportive is 1 (creditor-favorable); an Extraction-Oriented or Creditor-Adverse row with no
Supportive row is 5 (adverse), decided by the adverse rows; any other mix is 3; no row is Not
Scorable. With at least four dimensions scored the composite is the most adverse score and the
Sponsor / Governance Risk Level follows it (1 Low, 3 Medium, 5 High). With fewer, the composite
is Not Scorable and the level Insufficient Information, unless one adverse row rests on High
evidence (with or without a dimension label; its category and direction not Insufficient),
which sets High (r14's "one clearly High-risk documented action"). No weights, no
averages; the evidence quality of a dimension is the strongest among its deciding rows.

### T2D.9: risk-level drivers

The credit translations, row for row: theme, evidence, mechanic, implication, Evidence Quality
from the confidence level for level, Source Trace, and Countervailing Evidence from the logged
conflicts the row names (else `Insufficient Information: no logged conflict counters this
driver`).

## CONTEXT block and CP-1 figures

`context_block` lists `consumers` (CP-MODEL and every selected consumer of CP-1A, registry
order) and `cp1_facts`: the referencable facts (known, an amount, cited or calculated) of the
CP-1 head bound as an input of the ticket. The journal binds a settled (accepted or restricted)
CP-1 head as a context input of CP-1A (`execution.CONTEXT_PRODUCERS`), so the figures CP-1A
text references are lineage and go stale with CP-1. Without one, `cp1_facts` is empty and the
note says no figure may be written. CP-1A carries no amounts of its own.

## Bindings and delivery

`bindings/cp1a.py`: the issuer row of `company_description` as key/value rows (Issuer, Business
description, Country, Sector) and `operating_model` as a second tab of
`company-operating-model`; `ownership_register` and `revenue_business_mix` in
`company-profile`; `transaction_summary` and `events_timeline` as prose lines of
`transaction-summary` (owner code `Primary`); the credit translation, T2D.8, T2D.9, the
conflict log and the remaining registers in Evidence; the gaps ledger, downstream readiness and
T2D.11 in Limitations. `delivery.deliver_cp1a` publishes a standalone candidate and accepted
page with receipt `cp1a-delivery/1`, or a `rejected` delivery carrying the validator issues.

## Limits

- The keyvalue renderer joins a multi-column row's cells after its label, so a whole register
  in a keyvalue tab repeats its first cell; the drivers cannot continue the company rows in one
  list (one register per tab). The prose block shows one line per cell, with no column label.
- The prohibited-conclusion check is a phrase list; semantic review remains required.
- The scoring rule reads the model's direction and dimension labels; it does not check them.
- Live uptake (E1) and provider acceptance of the sent schema are the coordinator's to run.
