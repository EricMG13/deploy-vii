"""CP-5 evidence trace validator (task 8.4): one live step, `integrity_review`.

CP-5 reads the settled heads its attempt binds (every selected analyst, decision 0007 item 1)
and never rewrites one. Python runs the mechanical checks with the existing functions, never
re-implemented here (plan M8, MC-6):

- citation existence and quote match: `readiness.citation_issues` over every bound claim's and
  fact's citations against the prepared pack;
- claim figure resolution: `prose.issues` of each claim against its own module's facts;
- cross-module figure identity (new, ruling 5): facts sharing a `fact_id`, and figures sharing
  `(table_id, row_id, field, period)`, must agree in amount, unit, currency, scale and period.
  A disagreement is a finding; CP-5 writes no replacement value and repeats no amount;
- stale inputs: `execution.current_inputs` and each bound hash against its current head;
- gap propagation: `execution.blocked_ancestors` and `execution.inherited_limitations`, and a
  claim that rests on an unsettled fact without stating a limitation.

The model judges two things only: whether each material claim (every claim of an evaluated
head: `Module` carries no materiality flag) is materially supported by the upstream facts and
citations it names, and which claims of different modules contradict each other. It names
upstream evidence by reference only (ruling 2: no pack quote, no figure). A review that cannot
be completed (a stale or unreadable head, an unresolved reference, an unreviewed or doubly
reviewed claim) or a verdict inconsistent with Python's findings (`supported` over a claim or a
reference Python flags) is a validator issue: the step is rejected and, after its one repair,
the module settles `blocked` through the existing settle path (decision 0007; a valid
candidate is never settled `blocked` directly). Every finding (Python's, an unsupported or
partly supported claim, a contradiction) and every model gap is an own limitation, so CP-5
settles `restricted` (ruling 4); `IntegrityReport.status` is the status over the evaluated set
only (docs/frontend-direction-c.md, CP-5 row).

The journal path (`submit_cp5_step`) validates the one step and settles CP-5 with the Python
candidate in the same call, as `submit_cp1a_step` does for CP-1A. Registration in the shared
step tables is a separate change; nothing here needs it.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, get_args

from pydantic import Field, ValidationError

from deploy_vii import prose
from deploy_vii.business_context import Cell, Register, spelled
from deploy_vii.contracts import (
    Claim,
    Contract,
    Fact,
    Hash,
    Identifier,
    Input,
    Module,
    ReportTable,
    Run,
    TableColumn,
    TableRow,
    Text,
)
from deploy_vii.execution import (
    Attempt,
    Execution,
    Qualification,
    StepValidation,
    blocked_ancestors,
    current_inputs,
    inherited_limitations,
    text_sha256,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import citation_issues, shape_issues
from deploy_vii.registry import modules

MODULE_ID = "CP-5"
STEP_ID = "integrity_review"
CP5_STEPS = (STEP_ID,)
SCHEMA_VERSION = "integrity-review/1"
PROMOTED = Qualification(implementation="implemented")
# Bound but not evaluated: CP-0 is the source-readiness gate CP-5 requires, not an analyst
# (ruling 1: analysts' facts and claims only). The prepared pack is not a module.
NOT_EVALUATED = frozenset({"CP-0"})
SUBMISSION_INPUT = "integrity-submission"
# The attributes a figure must share wherever it appears (ruling 5; currency added, since the
# same amount in another currency is another figure).
FIGURE_FIELDS = ("amount", "unit", "currency", "scale", "period")

# --- the model-facing contract ---------------------------------------------------------------
# Plain `str` fields, as in `BusinessContextSubmission`: the validator holds references and
# text. Every field is required (no defaults); the enums are `Literal`s, so the schema carries
# them. Python assigns every finding, contradiction and gap id.

Support = Literal["supported", "partly_supported", "unsupported"]
Severity = Literal["Critical", "Material", "Minor"]


class ClaimRef(Contract):
    producer_module: str
    claim_ref: str  # a `Claim.claim_id` of that module's bound head


class ClaimReview(Contract):
    claim_ref: str
    producer_module: str
    support: Support
    rationale: str
    # Fact ids of the producer's head, or its citation refs `<claim_id>#c<n>` (CONTEXT lists
    # both); never a new quote.
    upstream_refs: tuple[str, ...]


class Contradiction(Contract):
    # `minItems: 2` in the sent schema only; the validator also requires two modules.
    claim_refs: tuple[ClaimRef, ...] = Field(json_schema_extra={"minItems": 2})
    nature: str
    rationale: str
    severity: Severity


class IntegrityGap(Contract):
    gap: str
    why_it_matters: str
    affected_modules: tuple[str, ...]
    severity: Severity
    action: str


class IntegritySubmission(Contract):
    """What the model returns for `integrity_review`; every field is required."""

    claim_reviews: tuple[ClaimReview, ...]
    contradictions: tuple[Contradiction, ...]
    gaps: tuple[IntegrityGap, ...]


# --- findings and the composed report ---------------------------------------------------------

FindingKind = Literal[
    "blocked_upstream",
    "empty_evaluated_set",
    "claim_citation",
    "fact_citation",
    "claim_figure",
    "unsettled_fact",
    "figure_identity",
    "unsupported_claim",
    "partly_supported_claim",
    "contradiction",
]
KINDS: tuple[FindingKind, ...] = get_args(FindingKind)
KIND_LABEL: Mapping[str, str] = {
    "blocked_upstream": "Blocked upstream",
    "empty_evaluated_set": "Empty evaluated set",
    "claim_citation": "Failed upstream citation",
    "fact_citation": "Failed upstream citation",
    "claim_figure": "Unresolved claim figure",
    "unsettled_fact": "Claim rests on an unsettled fact",
    "figure_identity": "Figure mismatch",
    "unsupported_claim": "Unsupported claim",
    "partly_supported_claim": "Partly supported claim",
    "contradiction": "Contradiction",
}
REVIEW_KINDS = frozenset({"unsupported_claim", "partly_supported_claim", "contradiction"})


class Finding(Contract):
    """One CP-5 finding, written by Python; the model's own words appear only in `detail` of
    a review finding, after validation."""

    kind: FindingKind
    modules: tuple[Identifier, ...]
    subject: Text
    detail: Text

    @property
    def where(self) -> str:
        if self.kind in {"blocked_upstream", "empty_evaluated_set", "contradiction"}:
            return self.subject
        if self.kind == "figure_identity":
            return f"{self.subject} ({', '.join(self.modules)})"
        return f"{self.modules[0]} {self.subject}"


class IntegrityReport(Contract):
    schema_version: Literal["integrity-review/1"] = "integrity-review/1"
    run: Run
    pack_sha256: Hash
    submission_sha256: Hash
    evaluated: tuple[Input, ...]  # the bound analyst heads evaluated, in registry order
    status: Literal["accepted", "restricted"]  # over the evaluated set only
    findings: tuple[Finding, ...]
    tables: tuple[ReportTable, ...]
    facts: tuple[Fact, ...]
    limitations: tuple[Text, ...]


# --- what one review evaluates --------------------------------------------------------------


@lru_cache(maxsize=1)
def _registry_order() -> Mapping[str, int]:
    return {item.module_id: index for index, item in enumerate(modules())}


def _rank(module_id: str) -> tuple[int, int, str]:
    """Registry order; the non-module inputs (the prepared pack) first."""
    order = _registry_order()
    return (module_id in order, order.get(module_id, 0), module_id)


@dataclass(frozen=True)
class ReviewScope:
    """The bound inputs of one CP-5 attempt and the analyst heads they name.

    `heads` are the bound module results other than `NOT_EVALUATED`, each exactly the module
    its input hash names, with its bound status. `blocked` is `execution.blocked_ancestors`
    over `inputs`; `inherited` is `execution.inherited_limitations` of the attempt; `issues`
    say why the review cannot be made (stale or unreadable inputs). `review_scope` builds one
    from the journal; a test may build one directly.
    """

    pack: PreparedPack
    inputs: tuple[Input, ...]
    heads: tuple[tuple[Input, Module], ...]
    blocked: frozenset[str] = frozenset()
    inherited: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ids = [item.input_id for item, _ in self.heads]
        if len(set(ids)) != len(ids):
            raise ValueError("A head is bound twice in the review scope")
        for item, head in self.heads:
            if item not in self.inputs:
                raise ValueError(f"Head {item.input_id} is not a bound input of the review")
            if head.module_id != item.input_id or head.content_hash() != item.sha256:
                raise ValueError(f"Head {item.input_id} is not the module its input names")
            if head.status != item.status:
                raise ValueError(f"Head {item.input_id} status differs from its bound status")
            if item.status == "blocked" and item.input_id not in self.blocked:
                raise ValueError(f"Blocked input {item.input_id} is missing from blocked")

    @property
    def evaluated(self) -> tuple[Module, ...]:
        """The heads CP-5 evaluates: every bound analyst head that is not blocked."""
        found = [head for item, head in self.heads if item.status != "blocked"]
        return tuple(sorted(found, key=lambda head: _rank(head.module_id)))

    def bound_modules(self) -> frozenset[str]:
        order = _registry_order()
        return frozenset(i.input_id for i in self.inputs if i.input_id in order) | self.blocked


def review_scope(store: Execution, attempt: Attempt) -> ReviewScope:
    """The scope of a CP-5 attempt, read from the journal: its bound inputs, the result blob
    each names, the blocked ancestors and the inherited limitations.

    A stale input (the bound hash is no longer the current head, or the current inputs differ)
    or an unreadable result is recorded in `issues`, which refuse the review: the journal's
    `ValueError` on a missing or tampered blob becomes that issue, so the review fails closed
    with the reason kept, never with a partial scope accepted."""
    snapshot = store.read()
    pack = store.pack(snapshot)
    issues: list[str] = []
    try:
        if current_inputs(snapshot, attempt.module_id) != attempt.inputs:
            issues.append("Stale inputs: the bound inputs are not the journal's current inputs")
    except ValueError as error:
        issues.append(f"Stale inputs: the current inputs cannot be derived: {error}")
    order = _registry_order()
    current = {head.module_id: head for head in snapshot.heads}
    heads: list[tuple[Input, Module]] = []
    for item in attempt.inputs:
        if item.input_id not in order or item.input_id in NOT_EVALUATED:
            continue
        head = current.get(item.input_id)
        if head is None or head.status == "stale" or head.result_sha256 != item.sha256:
            issues.append(f"Stale input {item.input_id}: the bound result is not its current head")
        try:
            result = store.result(item.sha256)
        except ValueError as error:
            issues.append(f"Unreadable upstream head {item.input_id}: {error}")
            continue
        if result.module_id != item.input_id or result.status != item.status:
            issues.append(f"Unreadable upstream head {item.input_id}: not the bound module")
            continue
        heads.append((item, result))
    try:
        inherited = inherited_limitations(snapshot, attempt, (), store.head_module)
    except ValueError as error:
        issues.append(f"Unreadable upstream head: inherited limitations: {error}")
        inherited = ()
    return ReviewScope(
        pack=pack,
        inputs=attempt.inputs,
        heads=tuple(heads),
        blocked=blocked_ancestors(snapshot, attempt.inputs),
        inherited=inherited,
        issues=tuple(dict.fromkeys(issues)),
    )


def citation_ref(claim_id: str, number: int) -> str:
    """How a review names a claim's citation: `<claim_id>#c<n>`, 1-based (`#` is outside the
    identifier alphabet, so it never collides with a fact id)."""
    return f"{claim_id}#c{number}"


def upstream_refs(head: Module) -> tuple[str, ...]:
    """The references a review of this head may name: its fact ids, then each claim's
    citation refs."""
    return (
        *(fact.fact_id for fact in head.facts),
        *(
            citation_ref(claim.claim_id, number)
            for claim in head.claims
            for number in range(1, len(claim.citations) + 1)
        ),
    )


def _claim_keys(scope: ReviewScope) -> tuple[tuple[str, str], ...]:
    """Every material claim of the evaluated set, (module, claim id), in canonical order."""
    return tuple(
        (head.module_id, claim_id)
        for head in scope.evaluated
        for claim_id in sorted(claim.claim_id for claim in head.claims)
    )


# --- the Python checks ------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityGroup:
    """Facts of two or more modules under one key; `differing` names the attributes that do
    not agree (empty when the figure is identical everywhere)."""

    basis: Literal["fact_id", "coordinate"]
    subject: str
    modules: tuple[str, ...]
    members: tuple[tuple[str, str], ...]  # (module, fact id)
    differing: tuple[str, ...]


def identity_groups(heads: Sequence[Module]) -> tuple[IdentityGroup, ...]:
    """Every key two modules share, where at least one member is a figure: by `fact_id` over
    all facts, and by `(table_id, row_id, field, period)` over figures. Both checks run on
    every pair (ruling 5), so a disagreement may be found under both keys."""
    pooled: dict[tuple[Literal["fact_id", "coordinate"], str], list[tuple[str, Fact]]] = {}
    for head in heads:
        for fact in head.facts:
            pooled.setdefault(("fact_id", f"fact_id {fact.fact_id}"), []).append(
                (head.module_id, fact)
            )
            if fact.amount is not None:
                where = f"{fact.table_id}/{fact.row_id}/{fact.field}/{fact.period}"
                pooled.setdefault(("coordinate", f"coordinate {where}"), []).append(
                    (head.module_id, fact)
                )
    groups: list[IdentityGroup] = []
    for (basis, subject), members in pooled.items():
        owners = {module_id for module_id, _ in members}
        if len(owners) < 2 or all(fact.amount is None for _, fact in members):
            continue
        differing = tuple(
            name for name in FIGURE_FIELDS if len({getattr(f, name) for _, f in members}) > 1
        )
        groups.append(
            IdentityGroup(
                basis=basis,
                subject=subject,
                modules=tuple(sorted(owners, key=_rank)),
                members=tuple(
                    sorted(
                        {(m, fact.fact_id) for m, fact in members},
                        key=lambda pair: (_rank(pair[0]), pair[1]),
                    )
                ),
                differing=differing,
            )
        )
    return tuple(sorted(groups, key=lambda group: (group.basis != "fact_id", group.subject)))


def _identity_finding(group: IdentityGroup) -> Finding:
    return Finding(
        kind="figure_identity",
        modules=group.modules,
        subject=group.subject,
        detail=(
            f"differs in {', '.join(group.differing)} between {', '.join(group.modules)}; "
            "CP-5 records the disagreement and writes no replacement value"
        ),
    )


def figure_identity(heads: Sequence[Module]) -> tuple[Finding, ...]:
    """The cross-module figure disagreements among `heads`, one finding per key."""
    return tuple(_identity_finding(g) for g in identity_groups(heads) if g.differing)


@dataclass(frozen=True)
class Unsettled:
    module_id: str
    claim_id: str
    fact_ids: tuple[str, ...]
    limited: bool


@dataclass(frozen=True)
class PythonChecks:
    """Python's findings over a scope, in canonical order, and what they touch: per claim the
    findings that make `supported` inconsistent; per module the references they flag."""

    findings: tuple[Finding, ...]
    claim_marks: Mapping[tuple[str, str], tuple[str, ...]]
    ref_marks: Mapping[str, frozenset[str]]
    groups: tuple[IdentityGroup, ...]
    unsettled: tuple[Unsettled, ...]


def _ordered(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    """De-duplicated, in a canonical order independent of head, claim and review order."""
    return tuple(
        sorted(
            dict.fromkeys(findings),
            key=lambda f: (KINDS.index(f.kind), [_rank(m) for m in f.modules], f.subject, f.detail),
        )
    )


def _finding(kind: FindingKind, module_id: str, subject: str, detail: str) -> Finding:
    return Finding(kind=kind, modules=(module_id,), subject=subject, detail=detail)


class _Checker:
    """Collects the findings over one scope and what each touches (`PythonChecks`)."""

    def __init__(self, scope: ReviewScope) -> None:
        self.sources = scope.pack.sources
        self.names = (scope.pack.run.issuer_name,)
        self.found: list[Finding] = []
        self.marks: dict[tuple[str, str], list[str]] = {}
        self.flagged: dict[str, dict[str, set[str]]] = {}
        self.referenced: dict[tuple[str, str], set[str]] = {}
        self.unsettled: list[Unsettled] = []

    def flag(self, module_id: str, ref: str, kind: str) -> None:
        self.flagged.setdefault(module_id, {}).setdefault(ref, set()).add(kind)

    def facts(self, head: Module) -> None:
        """`citation_issues` over every fact's citations."""
        for fact in head.facts:
            for issue in citation_issues(fact.citations, self.sources):
                self.found.append(
                    _finding("fact_citation", head.module_id, f"fact {fact.fact_id}", issue)
                )
                self.flag(head.module_id, fact.fact_id, "fact_citation")

    def claim(self, head: Module, claim: Claim, bound: Mapping[str, Fact]) -> None:
        """`citation_issues`, `prose.issues` and the unsettled-fact rule over one claim."""
        module_id, subject = head.module_id, f"claim {claim.claim_id}"
        own = [
            _finding("claim_citation", module_id, subject, issue)
            for issue in citation_issues(claim.citations, self.sources)
        ]
        for number, citation in enumerate(claim.citations, 1):
            if citation_issues((citation,), self.sources):
                self.flag(module_id, citation_ref(claim.claim_id, number), "claim_citation")
        own += [
            _finding("claim_figure", module_id, subject, issue)
            for issue in prose.issues(claim.text, bound, names=self.names)
        ]
        # `Claim.text` is validated run text, so it tokenizes; a reference that does not
        # resolve is a `claim_figure` finding above and names no fact here.
        named = {
            bound[run.text]
            for run in prose.tokenize(claim.text)
            if run.kind != "text" and run.text in bound
        }
        key = (module_id, claim.claim_id)
        self.referenced[key] = {fact.fact_id for fact in named}
        gaps = tuple(sorted(fact.fact_id for fact in named if fact.status != "known"))
        if gaps:
            limited = bool(claim.limitation)
            self.unsettled.append(Unsettled(module_id, claim.claim_id, gaps, limited))
            if not claim.limitation:
                detail = f"rests on unsettled fact {', '.join(gaps)} and states no limitation"
                own.append(_finding("unsettled_fact", module_id, subject, detail))
        self.found.extend(own)
        self.marks.setdefault(key, []).extend(f"{f.kind}: {f.detail}" for f in own)

    def identity(self, groups: Sequence[IdentityGroup]) -> None:
        for group in groups:
            if group.differing:
                self.found.append(_identity_finding(group))
                for module_id, fact_id in group.members:
                    self.flag(module_id, fact_id, "figure_identity")
        # A claim whose figures a finding flags is touched by it, as by its own findings.
        for key, fact_ids in self.referenced.items():
            flags = self.flagged.get(key[0], {})
            for fact_id in sorted(fact_ids):
                for kind in sorted(flags.get(fact_id, ()), key=KINDS.index):
                    self.marks.setdefault(key, []).append(f"{kind} on {fact_id}")


def python_checks(scope: ReviewScope) -> PythonChecks:
    """Every mechanical finding over the evaluated set, from the existing check functions."""
    checker = _Checker(scope)
    checker.found += [
        _finding(
            "blocked_upstream",
            module_id,
            module_id,
            "its outputs are outside the evaluated set and are not implied to pass",
        )
        for module_id in scope.blocked
    ]
    if not scope.evaluated:
        checker.found.append(
            Finding(
                kind="empty_evaluated_set",
                modules=(),
                subject="evaluated set",
                detail="no accepted or restricted analyst head is bound, so nothing was evaluated",
            )
        )
    for head in scope.evaluated:
        checker.facts(head)
        bound = prose.bind(head.facts)
        for claim in head.claims:
            checker.claim(head, claim, bound)
    groups = identity_groups(scope.evaluated)
    checker.identity(groups)
    return PythonChecks(
        findings=_ordered(checker.found),
        claim_marks={key: tuple(sorted(set(v))) for key, v in checker.marks.items() if v},
        ref_marks={m: frozenset(refs) for m, refs in checker.flagged.items()},
        groups=groups,
        unsettled=tuple(
            sorted(checker.unsettled, key=lambda item: (_rank(item.module_id), item.claim_id))
        ),
    )


# --- validation of the model's verdict --------------------------------------------------------


def _text_issues(path: str, text: str, names: Sequence[str]) -> list[str]:
    """Model prose is labels only: no figure and no reference (`prose.issues` against no
    facts); upstream evidence is named in `upstream_refs`."""
    if not text.strip():
        return [f"{path}: empty text"]
    return [f"{path}: {issue}" for issue in prose.issues(text, {}, names=names)]


def _resolve(
    path: str, module_id: str, claim_id: str, claims: Mapping[str, frozenset[str]]
) -> tuple[str, str] | str:
    """The (module, claim) a reference names, or the issue saying why it does not resolve."""
    if module_id not in claims:
        listed = ", ".join(claims) or "none"
        return f"{path}: producer_module {module_id} is not an evaluated module ({listed})"
    if claim_id not in claims[module_id]:
        return f"{path}: unresolved claim_ref {claim_id} in {module_id}"
    return (module_id, claim_id)


def _review_issues(
    scope: ReviewScope, submission: IntegritySubmission, checks: PythonChecks
) -> list[str]:
    names = (scope.pack.run.issuer_name,)
    evaluated = {head.module_id: head for head in scope.evaluated}
    claims = {m: frozenset(c.claim_id for c in head.claims) for m, head in evaluated.items()}
    refs = {m: frozenset(upstream_refs(head)) for m, head in evaluated.items()}
    issues: list[str] = []
    reviewed: dict[tuple[str, str], int] = {}
    for index, review in enumerate(submission.claim_reviews):
        path = f"claim_reviews[{index}]"
        issues.extend(_text_issues(f"{path}.rationale", review.rationale, names))
        key = _resolve(path, review.producer_module, review.claim_ref, claims)
        if isinstance(key, str):
            issues.append(key)
            continue
        reviewed[key] = reviewed.get(key, 0) + 1
        for ref in review.upstream_refs:
            if ref not in refs[key[0]]:
                issues.append(f"{path}: unresolved upstream_ref {ref} in {key[0]}")
        if review.support != "unsupported" and not review.upstream_refs:
            issues.append(f"{path}: a {review.support} verdict names no upstream_ref")
        if review.support == "supported":
            marked = checks.ref_marks.get(key[0], frozenset())
            touching = [
                *checks.claim_marks.get(key, ()),
                *(f"flagged upstream_ref {ref}" for ref in review.upstream_refs if ref in marked),
            ]
            if touching:
                issues.append(
                    f"{path}: {key[0]} {key[1]} cannot be supported over Python findings: "
                    + "; ".join(touching)
                )
    for (module_id, claim_id), count in reviewed.items():
        if count > 1:
            issues.append(f"{module_id} {claim_id} is reviewed more than once")
    missing = [key for key in _claim_keys(scope) if key not in reviewed]
    if missing:
        issues.append(
            "Incomplete review: unreviewed material claims: "
            + ", ".join(f"{module_id} {claim_id}" for module_id, claim_id in missing)
        )
    for index, item in enumerate(submission.contradictions):
        path = f"contradictions[{index}]"
        issues.extend(_text_issues(f"{path}.nature", item.nature, names))
        issues.extend(_text_issues(f"{path}.rationale", item.rationale, names))
        keys: list[tuple[str, str]] = []
        for number, claim_ref in enumerate(item.claim_refs):
            where = f"{path}.claim_refs[{number}]"
            key = _resolve(where, claim_ref.producer_module, claim_ref.claim_ref, claims)
            if isinstance(key, str):
                issues.append(key)
            else:
                keys.append(key)
        if len(set(keys)) != len(keys):
            issues.append(f"{path}: names a claim more than once")
        if len({named.producer_module for named in item.claim_refs}) < 2:
            issues.append(f"{path}: a contradiction names claims of at least two modules")
    bound = scope.bound_modules()
    for index, gap in enumerate(submission.gaps):
        path = f"gaps[{index}]"
        for name in ("gap", "why_it_matters", "action"):
            issues.extend(_text_issues(f"{path}.{name}", getattr(gap, name), names))
        for module_id in gap.affected_modules:
            if module_id not in bound:
                issues.append(f"{path}: {module_id} is not a bound module")
    return issues


def validate_integrity(scope: ReviewScope, submission: IntegritySubmission) -> tuple[str, ...]:
    """Every issue of `submission` over `scope`, in a stable order; empty when it composes.

    A scope that cannot be reviewed (stale or unreadable inputs) returns its own issues."""
    try:
        submission = IntegritySubmission.model_validate_json(submission.model_dump_json())
    except ValidationError as error:
        return shape_issues(error)
    if scope.issues:
        return scope.issues
    return tuple(dict.fromkeys(_review_issues(scope, submission, python_checks(scope))))


# --- composition -------------------------------------------------------------------------------


def _register(table_id: str, title: str, columns: str) -> Register:
    """A table from its column labels, `|`-separated; each field is the label in snake case.
    The first column is the row header."""
    labels = columns.split("|")
    fields = [re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_") for label in labels]
    return Register(table_id, title, tuple(zip(fields, labels, strict=True)))


# Ruling 3: the r14 ids with minimal Python-composed tables (the r14 CP-5 columns are not in
# the repository); the adaptation is recorded in `methods/cp5.md`.
REGISTERS: Mapping[str, Register] = {
    item.table_id: item
    for item in (
        _register("T5.1", "Evaluated set", "Input|Bound status|Bound SHA-256|Evaluation"),
        _register("T5.2", "Material claim register", "Claim|Module|Citations|Limitation"),
        _register("T5.3", "Citation trace", "Record|Module|Source trace|Result"),
        _register("T5.4", "Claim figure resolution", "Claim|Module|Result"),
        _register("T5.5", "Figure identity by fact id", "Fact id|Modules|Result"),
        _register("T5.6", "Figure identity by coordinate", "Coordinate|Modules|Result"),
        _register("T5.7", "Input currency", "Input|Bound status|Result"),
        _register("T5.8", "Gap propagation", "Item|Module|Result"),
        _register("T5.9", "Findings register", "Finding|Kind|Origin|Where|Detail"),
        _register(
            "T5B.1",
            "Material support review",
            "Claim|Module|Support|Upstream refs|Rationale",
        ),
        _register(
            "T5B.2",
            "Unsupported and partly supported claims",
            "Claim|Module|Support|Rationale",
        ),
        _register(
            "T5B.3",
            "Cross-module contradictions",
            "Contradiction|Claims|Nature|Severity|Rationale",
        ),
        _register(
            "T5B.4",
            "Verdict consistency",
            "Claim|Module|Python findings|Support|Result",
        ),
        _register(
            "T5B.5",
            "Integrity gaps",
            "Gap ID|Gap|Why it matters|Affected modules|Severity|Action",
        ),
        _register("T5B.6", "Module integrity status", "Module|Head status|CP-5 findings|Result"),
        _register("T5B.7", "Report-level limitations", "Limitation ID|Limitation|Origin"),
        _register("T5B.8", "Integrity verdict", "Item|Value"),
    )
}
TABLE_IDS: tuple[str, ...] = tuple(REGISTERS)
SUPPORT_WORD: Mapping[str, str] = {
    "supported": "Supported",
    "partly_supported": "Partly supported",
    "unsupported": "Unsupported",
}
SCOPE_NOTE = (
    "Describes the evaluated set only: a module outside it, unrun, blocked or not selected, "
    "is not implied to pass"
)
NONE_STATED = "None stated"
Row = tuple[str, str, Sequence[Cell]]


class _Tables:
    """Writes the tables as text facts: Python text, or validated model text (`judged`)."""

    def __init__(self) -> None:
        self.tables: list[ReportTable] = []
        self.facts: list[Fact] = []

    def add(self, register: Register, rows: Sequence[Row]) -> None:
        columns = register.columns[1:]
        if not rows:
            reason = f"None in this CP-5 review ({register.title.lower()})"
            empty = Cell(None, reason=reason, status="not_applicable")
            rows = (("none", "None", tuple(empty for _ in columns)),)
        table_rows: list[TableRow] = []
        for row_id, label, cells in rows:
            ids: list[str] = []
            for (field, heading), cell in zip(columns, cells, strict=True):
                fact_id = f"{register.table_id}.{row_id}.{field}"
                self.facts.append(
                    Fact(
                        fact_id=fact_id,
                        label=heading,
                        table_id=register.table_id,
                        row_id=row_id,
                        field=field,
                        text=cell.text,
                        status="known" if cell.text is not None else cell.status,
                        value_class="analyst_judgment" if cell.judged else None,
                        limitation=cell.reason if cell.text is None else None,
                    )
                )
                ids.append(fact_id)
            table_rows.append(TableRow(row_id=row_id, label=label, fact_ids=tuple(ids)))
        self.tables.append(
            ReportTable(
                table_id=register.table_id,
                title=register.title,
                columns=tuple(TableColumn(field=f, label=label) for f, label in columns),
                rows=tuple(table_rows),
                row_header=register.columns[0][1],
            )
        )


def _numbered(rows: Iterable[tuple[str, Sequence[Cell]]]) -> list[Row]:
    return [(f"r{index:03d}", label, cells) for index, (label, cells) in enumerate(rows, 1)]


def _review_findings(submission: IntegritySubmission) -> list[Finding]:
    """The findings the validated verdict carries, in Python's words with the model's
    rationale: an unsupported or partly supported claim, and each contradiction."""
    found: list[Finding] = []
    for review in submission.claim_reviews:
        if review.support == "supported":
            continue
        word = SUPPORT_WORD[review.support].lower()
        kind: FindingKind = (
            "unsupported_claim" if review.support == "unsupported" else "partly_supported_claim"
        )
        detail = f"marked {word} by the integrity review: {review.rationale}"
        found.append(_finding(kind, review.producer_module, f"claim {review.claim_ref}", detail))
    found.extend(_contradiction_finding(item) for item in submission.contradictions)
    return found


def _contradiction_finding(item: Contradiction) -> Finding:
    pairs = sorted(
        {(ref.producer_module, ref.claim_ref) for ref in item.claim_refs},
        key=lambda pair: (_rank(pair[0]), pair[1]),
    )
    return Finding(
        kind="contradiction",
        modules=tuple(sorted({m for m, _ in pairs}, key=_rank)),
        subject="; ".join(f"{m} {c}" for m, c in pairs),
        detail=f"{item.severity} contradiction ({item.nature}): {item.rationale}",
    )


class _Composition:
    """The state the table writers share: scope, checks, verdict and numbered findings."""

    def __init__(
        self,
        scope: ReviewScope,
        submission: IntegritySubmission,
        checks: PythonChecks,
        findings: tuple[Finding, ...],
    ) -> None:
        self.scope, self.submission, self.checks = scope, submission, checks
        self.findings = findings
        self.ids = {f: f"CP-5-FINDING-{index:03d}" for index, f in enumerate(findings, 1)}
        self.reviews = {(r.producer_module, r.claim_ref): r for r in submission.claim_reviews}
        self.claims = {
            (head.module_id, claim.claim_id): claim
            for head in scope.evaluated
            for claim in head.claims
        }
        self.out = _Tables()

    def details(self, kind: str, module_id: str, subject: str) -> list[str]:
        return [
            f.detail
            for f in self.findings
            if f.kind == kind and f.modules[:1] == (module_id,) and f.subject == subject
        ]

    def of_module(self, module_id: str) -> list[str]:
        return [self.ids[f] for f in self.findings if module_id in f.modules]


def _inputs_tables(c: _Composition) -> None:
    scope = c.scope
    order = _registry_order()
    evaluated = {head.module_id for head in scope.evaluated}

    def evaluation(item: Input) -> str:
        if item.input_id not in order:
            return "Prepared pack: the citation checks read its sources"
        if item.input_id in NOT_EVALUATED:
            return "Source-readiness gate: bound, not an analyst; outside the evaluated set"
        if item.input_id in evaluated:
            return "Evaluated"
        return "Blocked upstream: outside the evaluated set"

    inputs = sorted(scope.inputs, key=lambda item: _rank(item.input_id))
    c.out.add(
        REGISTERS["T5.1"],
        _numbered(
            (i.input_id, (Cell(i.status), Cell(i.sha256), Cell(evaluation(i)))) for i in inputs
        ),
    )
    currency = "Bound as listed; a stale bound input refuses the review, and none is recorded"
    c.out.add(
        REGISTERS["T5.7"],
        _numbered((i.input_id, (Cell(i.status), Cell(currency))) for i in inputs),
    )


def _claim_tables(c: _Composition) -> None:
    keys = _claim_keys(c.scope)

    def trace(module_id: str, claim_id: str) -> str:
        claim = c.claims[(module_id, claim_id)]
        return "; ".join(
            f"{citation_ref(claim_id, n)} {x.source_id} {x.locator}"
            for n, x in enumerate(claim.citations, 1)
        )

    def result(kind: str, module_id: str, subject: str, clean: str) -> str:
        found = c.details(kind, module_id, subject)
        return f"Fails: {'; '.join(found)}" if found else clean

    c.out.add(
        REGISTERS["T5.2"],
        _numbered(
            (
                f"{m} {k}",
                (
                    Cell(m),
                    Cell(trace(m, k) or "No citation"),
                    Cell(c.claims[(m, k)].limitation or NONE_STATED),
                ),
            )
            for m, k in keys
        ),
    )
    holds = "Holds in the prepared pack"
    claim_rows = [
        (
            f"{m} claim {k}",
            (Cell(m), Cell(trace(m, k)), Cell(result("claim_citation", m, f"claim {k}", holds))),
        )
        for m, k in keys
        if c.claims[(m, k)].citations
    ]
    fact_rows = [
        (
            f"{head.module_id} fact {fact.fact_id}",
            (
                Cell(head.module_id),
                Cell("; ".join(f"{x.source_id} {x.locator}" for x in fact.citations)),
                Cell(result("fact_citation", head.module_id, f"fact {fact.fact_id}", holds)),
            ),
        )
        for head in c.scope.evaluated
        for fact in sorted(head.facts, key=lambda item: item.fact_id)
        if c.details("fact_citation", head.module_id, f"fact {fact.fact_id}")
    ]
    c.out.add(REGISTERS["T5.3"], _numbered((*claim_rows, *fact_rows)))
    resolves = "Every figure reference resolves to the module's own facts"
    c.out.add(
        REGISTERS["T5.4"],
        _numbered(
            (f"{m} {k}", (Cell(m), Cell(result("claim_figure", m, f"claim {k}", resolves))))
            for m, k in keys
        ),
    )


def _identity_tables(c: _Composition) -> None:
    same = "Identical amount, unit, currency, scale and period"

    def rows(basis: str) -> list[Row]:
        return _numbered(
            (
                group.subject.split(" ", 1)[1],
                (
                    Cell(", ".join(group.modules)),
                    Cell(
                        f"Differs in {', '.join(group.differing)}: a finding; no replacement "
                        "value is written"
                        if group.differing
                        else same
                    ),
                ),
            )
            for group in c.checks.groups
            if group.basis == basis
        )

    c.out.add(REGISTERS["T5.5"], rows("fact_id"))
    c.out.add(REGISTERS["T5.6"], rows("coordinate"))


def _gap_tables(c: _Composition) -> None:
    scope = c.scope
    rows: list[tuple[str, Sequence[Cell]]] = [
        (m, (Cell(m), Cell("Blocked upstream: outside the evaluated set")))
        for m in sorted(scope.blocked, key=_rank)
    ]
    for item in c.checks.unsettled:
        state = "the claim states its limitation" if item.limited else "no limitation: a finding"
        rows.append(
            (
                f"{item.module_id} claim {item.claim_id}",
                (
                    Cell(item.module_id),
                    Cell(f"Rests on unsettled fact {', '.join(item.fact_ids)}; {state}"),
                ),
            )
        )
    rows += [
        ("Inherited limitation", (Cell("Bound inputs"), Cell(text))) for text in scope.inherited
    ]
    c.out.add(REGISTERS["T5.8"], _numbered(rows))
    c.out.add(
        REGISTERS["T5.9"],
        [
            (
                f"f{index:03d}",
                c.ids[f],
                (
                    Cell(KIND_LABEL[f.kind]),
                    Cell("Integrity review" if f.kind in REVIEW_KINDS else "Python check"),
                    Cell(f.where),
                    Cell(f.detail, judged=f.kind in REVIEW_KINDS),
                ),
            )
            for index, f in enumerate(c.findings, 1)
        ],
    )


def _verdict_tables(c: _Composition) -> None:
    reviews = [c.reviews[key] for key in _claim_keys(c.scope)]

    def refs(review: ClaimReview) -> str:
        return ", ".join(review.upstream_refs) or "None named"

    c.out.add(
        REGISTERS["T5B.1"],
        _numbered(
            (
                f"{r.producer_module} {r.claim_ref}",
                (
                    Cell(r.producer_module),
                    Cell(SUPPORT_WORD[r.support]),
                    Cell(refs(r)),
                    Cell(r.rationale, judged=True),
                ),
            )
            for r in reviews
        ),
    )
    c.out.add(
        REGISTERS["T5B.2"],
        _numbered(
            (
                f"{r.producer_module} {r.claim_ref}",
                (
                    Cell(r.producer_module),
                    Cell(SUPPORT_WORD[r.support]),
                    Cell(r.rationale, judged=True),
                ),
            )
            for r in reviews
            if r.support != "supported"
        ),
    )
    # One row per distinct contradiction, in finding order (an exact repeat is one finding).
    items = {_contradiction_finding(item): item for item in c.submission.contradictions}
    c.out.add(
        REGISTERS["T5B.3"],
        [
            (
                f"x{index:03d}",
                c.ids[f],
                (
                    Cell(f.subject),
                    Cell(items[f].nature, judged=True),
                    Cell(items[f].severity),
                    Cell(items[f].rationale, judged=True),
                ),
            )
            for index, f in enumerate((f for f in c.findings if f in items), 1)
        ],
    )

    def consistency(review: ClaimReview) -> tuple[str, str]:
        marks = c.checks.claim_marks.get((review.producer_module, review.claim_ref), ())
        if not marks:
            return "None", "Consistent: no Python finding touches the claim"
        return "; ".join(marks), "Consistent: not marked supported over its Python findings"

    c.out.add(
        REGISTERS["T5B.4"],
        _numbered(
            (
                f"{r.producer_module} {r.claim_ref}",
                (
                    Cell(r.producer_module),
                    Cell(consistency(r)[0]),
                    Cell(SUPPORT_WORD[r.support]),
                    Cell(consistency(r)[1]),
                ),
            )
            for r in reviews
        ),
    )
    c.out.add(
        REGISTERS["T5B.5"],
        [
            (
                f"g{index:03d}",
                f"CP-5-GAP-{index:03d}",
                (
                    Cell(g.gap, judged=True),
                    Cell(g.why_it_matters, judged=True),
                    Cell(", ".join(g.affected_modules) or "Report level"),
                    Cell(g.severity),
                    Cell(g.action, judged=True),
                ),
            )
            for index, g in enumerate(c.submission.gaps, 1)
        ],
    )


def _status_tables(c: _Composition, own: Mapping[str, str], status: str) -> None:
    """T5B.6 to T5B.8; `own` maps each own limitation to its origin."""
    scope = c.scope
    statuses = {item.input_id: item.status for item, _ in scope.heads}
    evaluated = [head.module_id for head in scope.evaluated]
    shown = sorted(set(statuses) | scope.blocked, key=_rank)

    def result(module_id: str) -> str:
        if module_id not in evaluated:
            return "Blocked upstream: not evaluated"
        return "Evaluated with findings" if c.of_module(module_id) else "Evaluated: no finding"

    c.out.add(
        REGISTERS["T5B.6"],
        _numbered(
            (
                m,
                (
                    Cell(statuses.get(m, "blocked (up the input chain)")),
                    Cell(", ".join(c.of_module(m)) or "None"),
                    Cell(result(m)),
                ),
            )
            for m in shown
        ),
    )
    rows = [
        (f"L{index:03d}", (Cell(text), Cell(origin)))
        for index, (text, origin) in enumerate(own.items(), 1)
    ]
    rows += [
        (f"L{index:03d}", (Cell(text), Cell("Inherited")))
        for index, text in enumerate(scope.inherited, len(rows) + 1)
    ]
    c.out.add(REGISTERS["T5B.7"], _numbered(rows))
    outside = sorted(
        {i.input_id for i in scope.inputs if i.input_id in NOT_EVALUATED} | scope.blocked,
        key=_rank,
    )
    c.out.add(
        REGISTERS["T5B.8"],
        [
            ("status", "Status", (Cell(f"{status.capitalize()} over the evaluated set"),)),
            ("evaluated", "Evaluated set", (Cell(", ".join(evaluated) or "None"),)),
            ("not_evaluated", "Not evaluated", (Cell(", ".join(outside) or "None"),)),
            ("scope", "Scope", (Cell(SCOPE_NOTE),)),
        ],
    )


def integrity_review(scope: ReviewScope, submission: IntegritySubmission) -> IntegrityReport:
    """The composed CP-5 review of a valid submission; raises ValueError on any issue."""
    issues = validate_integrity(scope, submission)
    if issues:
        raise ValueError("; ".join(issues))
    submission = IntegritySubmission.model_validate_json(submission.model_dump_json())
    checks = python_checks(scope)
    findings = _ordered((*checks.findings, *_review_findings(submission)))
    c = _Composition(scope, submission, checks, findings)
    own: dict[str, str] = {}
    for f in findings:
        own.setdefault(f"{c.ids[f]} {KIND_LABEL[f.kind]}: {f.where}: {f.detail}", "CP-5 finding")
    for gap in submission.gaps:
        own.setdefault(f"Gap ({gap.severity}): {gap.gap}", "CP-5 gap")
    limitations = tuple(own)
    status: Literal["accepted", "restricted"] = "restricted" if limitations else "accepted"
    _inputs_tables(c)
    _claim_tables(c)
    _identity_tables(c)
    _gap_tables(c)
    _verdict_tables(c)
    _status_tables(c, own, status)
    tables = sorted(c.out.tables, key=lambda table: TABLE_IDS.index(table.table_id))
    order = {table.table_id: index for index, table in enumerate(tables)}
    evaluated = {head.module_id for head in scope.evaluated}
    return IntegrityReport(
        run=scope.pack.run,
        pack_sha256=scope.pack.content_hash(),
        submission_sha256=submission.content_hash(),
        evaluated=tuple(
            sorted(
                (item for item, _ in scope.heads if item.input_id in evaluated),
                key=lambda item: _rank(item.input_id),
            )
        ),
        status=status,
        findings=findings,
        tables=tuple(tables),
        facts=tuple(sorted(c.out.facts, key=lambda fact: order[fact.table_id])),
        limitations=limitations,
    )


# --- the module, the journal and the CONTEXT block ---------------------------------------------


def cp5_module(report: IntegrityReport, inputs: Sequence[Input], attempt: int) -> Module:
    """The CP-5 candidate: the report's tables and own limitations bound to `inputs`."""
    run = report.run
    return Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id=MODULE_ID,
        inputs=(*inputs, Input(input_id=SUBMISSION_INPUT, sha256=report.submission_sha256)),
        facts=report.facts,
        tables=report.tables,
        limitations=report.limitations,
        attempt=attempt,
    )


def _validate_step(store: Execution, attempt: Attempt) -> StepValidation:
    try:
        submission = IntegritySubmission.model_validate_json(
            store.payload(attempt.steps[0].payload_sha256)
        )
    except ValidationError as error:
        return StepValidation(issues=shape_issues(error))
    scope = review_scope(store, attempt)
    issues = validate_integrity(scope, submission)
    if issues:
        return StepValidation(issues=issues)
    return StepValidation(output=integrity_review(scope, submission).model_dump_json())


def submit_cp5_step(store: Execution, ticket_id: str, step_id: str, payload: str) -> Attempt:
    """Retain the one `integrity_review` response, validate it, then settle CP-5 with the Python
    candidate (as `submit_cp1a_step`). An invalid step finishes the attempt rejected (blocked on
    its repair); a crash after the step resumes from the retained valid step."""
    if step_id != STEP_ID:
        raise ValueError(f"CP-5 has one step, {STEP_ID}")
    attempt = next((a for a in store.read().attempts if a.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != MODULE_ID or attempt.status != "pending":
        raise ValueError("Ticket is absent, finished or belongs to another module")
    if attempt.steps and attempt.steps[0].payload_sha256 != text_sha256(payload):
        raise ValueError("Ticket already retains a different response; resume or interrupt")
    if not attempt.steps or attempt.steps[0].status == "pending":
        attempt = store.submit_step(
            ticket_id,
            MODULE_ID,
            CP5_STEPS,
            STEP_ID,
            payload,
            lambda _pack, current: _validate_step(store, current),
        )
    if attempt.status == "finished":
        return attempt
    outcome = _validate_step(store, attempt)
    if outcome.issues or not outcome.retained_as(attempt.steps[0]):
        raise ValueError("Retained CP-5 output differs from trusted validation")
    report = IntegrityReport.model_validate_json(outcome.output or "")
    candidate = cp5_module(report, attempt.inputs, attempt.number)
    return store.finish(
        ticket_id,
        candidate.model_dump_json(),
        lambda supplied: () if supplied == candidate else ("CP-5 candidate differs",),
        qualification=PROMOTED,
    )


def _fact_entry(fact: Fact) -> dict[str, object]:
    return {
        "ref": fact.fact_id,
        "label": fact.label,
        "table_id": fact.table_id,
        "row_id": fact.row_id,
        "field": fact.field,
        "period": fact.period,
        "status": fact.status,
        # Python's spelling of a settled value; an unsettled fact shows its limitation only.
        "shown": spelled(fact) if fact.status == "known" else None,
        "limitation": fact.limitation,
    }


def context_block(scope: ReviewScope) -> dict[str, object]:
    """What the `integrity_review` CONTEXT block states, all Python's: per bound analyst head
    its status, facts (Python's spelling), claims with their citation refs and the Python
    findings that touch each, limitations and inherited limitations; the claims to review; the
    Python findings; and the pack's source list. The model retypes no figure and no quote."""
    checks = python_checks(scope)
    evaluated = {head.module_id for head in scope.evaluated}
    heads = sorted(scope.heads, key=lambda pair: _rank(pair[0].input_id))
    return {
        "note": (
            "CP-5 reviews the evaluated set only. Python has checked citations, claim figures, "
            "cross-module figure identity, stale inputs and gap propagation; its findings are "
            "listed. Judge material support per claim and cross-module contradictions only, "
            "and name upstream evidence by `ref` alone."
        ),
        "sources": [
            {"source_id": s.source_id, "name": s.name, "status": s.status}
            for s in scope.pack.sources
        ],
        "modules": [
            {
                "module_id": head.module_id,
                "status": item.status,
                "evaluated": head.module_id in evaluated,
                "facts": [_fact_entry(fact) for fact in head.facts],
                "claims": [
                    {
                        "claim_id": claim.claim_id,
                        "text": claim.text,
                        "limitation": claim.limitation,
                        "citations": [
                            {
                                "ref": citation_ref(claim.claim_id, number),
                                "source_id": citation.source_id,
                                "locator": citation.locator,
                                "quote": citation.quote,
                            }
                            for number, citation in enumerate(claim.citations, 1)
                        ],
                        "python_findings": list(
                            checks.claim_marks.get((head.module_id, claim.claim_id), ())
                        ),
                    }
                    for claim in head.claims
                ],
                "limitations": list(head.limitations),
                "inherited_limitations": list(head.inherited_limitations),
            }
            for item, head in heads
        ],
        "claims_to_review": [[m, c] for m, c in _claim_keys(scope)],
        "python_findings": [
            f"{KIND_LABEL[f.kind]}: {f.where}: {f.detail}" for f in checks.findings
        ],
        "blocked_upstream": sorted(scope.blocked, key=_rank),
        "inherited_limitations": list(scope.inherited),
    }
