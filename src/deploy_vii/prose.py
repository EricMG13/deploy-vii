"""Run text: model prose whose numbers appear only as resolved references (decision 0005 MC-2).

``Claim.text`` of every module is run text, and CP-1 narrative prose obeys the same label
rule with no references (its numbers enter as evidence parts). Grammar:

- ``{<ref>}`` or ``{<ref>|<unit>}`` is a figure reference; ``[<ref>]`` is a chip: a gap run
  when ``<ref>`` names a gap, a reference chip otherwise.
- ``<ref>`` follows ``contracts.Identifier``: ``[A-Za-z0-9][A-Za-z0-9_.:-]*``, at most 160
  characters. In a module it is a ``Fact.fact_id`` (a table cell is a fact, so this is also
  how a table row's value is referenced) or a ``Fact.calculation_id`` that exactly one fact
  carries; a gap is an unsettled fact (status other than ``known``). No new id space.
- Braces and square brackets are reserved: one outside a well-formed reference is malformed.
- Outside references, a numeric character is allowed only inside a label (``LABELS``) or a
  supplied name (the run's issuer name). Any other numeric token is a bare figure.

Python resolves and spells every reference (``resolve``); the model never supplies a number.
"""

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from deploy_vii.contracts import Fact, Module

_ID = r"[A-Za-z0-9][A-Za-z0-9_.:-]*"
_ID_LENGTH = 160  # contracts.Identifier max_length
_TOKEN = re.compile(rf"\{{(?P<figure>{_ID})(?:\|(?P<unit>[^{{}}\[\]|]+))?\}}|\[(?P<chip>{_ID})\]")
_RESERVED = re.compile(r"[{}\[\]]")

# Boundaries: a label never starts or ends inside a word or a number.
_B = r"(?<![0-9A-Za-z])"
_E = r"(?![0-9A-Za-z])"
_YEAR = r"(?:19|20)[0-9]{2}"
# A bare year is a detached token: a percent sign after it makes a figure (1900%), as a unit
# letter already did (1900x, 1900bn) (task 7.10 item 15).
_YEAR_E = r"(?![0-9A-Za-z%])"
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?"
)
_DAY = r"(?:[1-9]|[12][0-9]|3[01])"
_INSTRUMENT_WORD = (
    r"(?i:senior|junior|secured|unsecured|subordinated|first-lien|second-lien|first|second|"
    r"lien|priority|guaranteed|convertible|exchangeable|fixed-rate|floating-rate|PIK|toggle)"
)
_INSTRUMENT_NOUN = rf"(?:(?i:notes?|bonds?|debentures?)|{_YEAR}s)"
_ITEM = r"[0-9]{1,2}[A-Z]?"
_ITEM_JOIN = r"(?:-|\u2013|/|, and |, | and )"

# The allowed labels. Everything numeric that none of these covers is a figure.
LABELS: Mapping[str, re.Pattern[str]] = MappingProxyType(
    {
        # FY2025, FY25, FY2025/26, CY2026, Q2, H1, 30 June 2026, June 30, 2026, 2026-06-30,
        # 2026.
        "period": re.compile(
            "|".join(
                (
                    rf"{_B}(?:FY|CY) ?(?:{_YEAR}|[0-9]{{2}})(?:/(?:{_YEAR}|[0-9]{{2}}))?{_E}",
                    rf"{_B}(?:Q[1-4]|H[12]){_E}",
                    rf"{_B}{_DAY} {_MONTH} {_YEAR}{_E}",
                    rf"{_B}{_MONTH} {_DAY}, {_YEAR}{_E}",
                    rf"{_B}{_YEAR}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]){_E}",
                    rf"{_B}{_YEAR}{_YEAR_E}",
                )
            )
        ),
        # Filing labels: 10-K, 10-Q, 8-K, 20-F (and 6-K, 40-F, S-1, F-1), with an /A amendment
        # or plural; an SEC file number (001-36629); a regulation (Regulation 14A).
        "filing": re.compile(
            "|".join(
                (
                    rf"{_B}(?:10-K|10-Q|8-K|20-F|6-K|40-F|S-[1348]|F-[1-4])(?:/A|s)?{_E}",
                    rf"{_B}[0-9]{{3}}-[0-9]{{5}}{_E}",
                    rf"{_B}Regulation [0-9]{{1,3}}[A-Z]?{_E}",
                )
            )
        ),
        # A coupon with an instrument noun (6.50% notes due 2032, 7.125% senior secured 2032s),
        # a maturity shorthand (2032s) and a tranche (Term Loan B-2, Tranche B-1).
        "instrument": re.compile(
            "|".join(
                (
                    rf"{_B}[0-9]{{1,2}}(?:\.[0-9]{{1,3}})?%(?: {_INSTRUMENT_WORD})* "
                    rf"{_INSTRUMENT_NOUN}{_E}(?: due {_YEAR}{_E})?",
                    rf"{_B}{_YEAR}s{_E}",
                    rf"{_B}(?:Term Loan|Tranche) [A-Z]-?[0-9]{{1,2}}{_E}",
                )
            )
        ),
        # Section labels: Item 1A, Note 12, Section 4.03(a), Exhibit 10.1, Rule 144A; plural
        # Items with ranges and lists (Items 10-14, Items 7, 7A, 8, Items 7/7A); page locators
        # (page 16, pages 16-18, a 195-page filing).
        "section": re.compile(
            "|".join(
                (
                    rf"{_B}(?:Item|Note|Section|Article|Schedule|Exhibit|Rule|Part|Chapter|Clause) "
                    rf"[0-9]{{1,4}}[A-Z]?(?:\.[0-9]{{1,3}})*(?:\([a-z0-9]{{1,4}}\))*(?![0-9A-Za-z(])",
                    rf"{_B}Items {_ITEM}(?:{_ITEM_JOIN}{_ITEM})*{_E}",
                    rf"{_B}[Pp]ages? [0-9]{{1,4}}(?:(?:-|\u2013)[0-9]{{1,4}})?{_E}",
                    rf"{_B}page:[0-9]{{1,4}}{_E}",
                    rf"{_B}[0-9]{{1,4}}-page{_E}",
                )
            )
        ),
        # Pack-coverage counts: how much of the Source Pack was read (195 of 195, 195 pages,
        # 195 located spans). They describe pack structure, not the issuer, so they are labels.
        # A duration (120 days) or any other bare count stays a figure.
        "coverage": re.compile(
            "|".join(
                (
                    rf"{_B}[0-9]{{1,5}} of [0-9]{{1,5}}{_E}",
                    rf"{_B}[0-9]{{1,5}} pages?{_E}",
                    rf"{_B}[0-9]{{1,6}} located spans?{_E}",
                )
            )
        ),
        # 2nd, r14, v2.1, CP-1, CP-1A.
        "ordinal": re.compile(
            "|".join(
                (
                    rf"{_B}[0-9]{{1,3}}(?:st|nd|rd|th){_E}",
                    rf"{_B}r[0-9]{{1,3}}{_E}",
                    rf"{_B}v[0-9]{{1,3}}(?:\.[0-9]{{1,3}}){{0,2}}{_E}",
                    rf"{_B}CP-[0-9]{{1,2}}[A-Z]?{_E}",
                )
            )
        ),
    }
)
_WORD = re.compile(r"\S+")
_PUNCTUATION = ".,;:!?()\"'"

RunKind = Literal["text", "ref", "gap"]


@dataclass(frozen=True)
class Run:
    """One token of run text. ``text`` is literal text, or the reference id of a ref/gap run.

    ``figure`` is set for ``{ref|unit}`` (a number with its unit) and clear for a ``[ref]`` chip.
    """

    kind: RunKind
    text: str
    unit: str | None = None
    figure: bool = False


def tokenize(text: str, *, gaps: Collection[str] = ()) -> tuple[Run, ...]:
    """Split run text into literal text and references; raise on malformed reference syntax."""
    runs: list[Run] = []
    last = 0
    for match in _TOKEN.finditer(text):
        literal = text[last : match.start()]
        if _RESERVED.search(literal):
            raise ValueError("Malformed run text: unbalanced or empty reference")
        if literal:
            runs.append(Run(kind="text", text=literal))
        ref = match.group("figure") or match.group("chip")
        if len(ref) > _ID_LENGTH:
            raise ValueError(f"Malformed run text: reference longer than {_ID_LENGTH} characters")
        if match.group("figure"):
            unit = match.group("unit")
            if unit is not None and not unit.strip():
                raise ValueError("Malformed run text: empty unit")
            runs.append(Run(kind="ref", text=ref, unit=unit and unit.strip(), figure=True))
        else:
            runs.append(Run(kind="gap" if ref in gaps else "ref", text=ref))
        last = match.end()
    tail = text[last:]
    if _RESERVED.search(tail):
        raise ValueError("Malformed run text: unbalanced or empty reference")
    if tail:
        runs.append(Run(kind="text", text=tail))
    return tuple(runs)


def valid_syntax(value: str) -> str:
    """``Claim.text`` validator: well-formed references; resolution needs the module's facts."""
    tokenize(value)
    return value


def bare_figures(text: str, *, names: Collection[str] = ()) -> tuple[str, ...]:
    """Numeric tokens of literal text that no label and no supplied name covers."""
    covered = [False] * len(text)
    spans = [m.span() for pattern in LABELS.values() for m in pattern.finditer(text)]
    for name in names:
        if name:
            spans += [m.span() for m in re.finditer(re.escape(name), text)]
    for start, end in spans:
        covered[start:end] = [True] * (end - start)
    found: list[str] = []
    for word in _WORD.finditer(text):
        start, token = word.start(), word.group()
        if any(char.isnumeric() and not covered[start + at] for at, char in enumerate(token)):
            found.append(token.strip(_PUNCTUATION) or token)
    return tuple(dict.fromkeys(found))


def _run_issues(
    run: Run, *, refs: Collection[str], gaps: Collection[str], names: Collection[str]
) -> list[str]:
    """Issues of one token: bare figures in literal text, or a reference that cannot resolve."""
    if run.kind == "text":
        return [f"Bare figure: {token}" for token in bare_figures(run.text, names=names)]
    if run.figure and run.text in gaps:
        return [f"Figure reference names a gap: {run.text}"]
    if run.kind == "ref" and run.text not in refs:
        return [f"Unresolved reference: {run.text}"]
    return []


def check(
    text: str,
    *,
    refs: Collection[str],
    gaps: Collection[str],
    names: Collection[str] = (),
) -> tuple[str, ...]:
    """Issues of run text against the ids it may reference, in reading order.

    ``refs`` are the resolvable figure and chip ids, ``gaps`` the gap ids, ``names`` literal
    names whose digits are not figures (the issuer name).
    """
    try:
        runs = tokenize(text, gaps=gaps)
    except ValueError as error:
        return (str(error),)
    found = [i for run in runs for i in _run_issues(run, refs=refs, gaps=gaps, names=names)]
    return tuple(dict.fromkeys(found))


def bind(facts: Iterable["Fact"]) -> dict[str, "Fact"]:
    """Reference id -> fact: every fact id, and each calculation id that one fact alone carries.

    A calculation id carried by several facts, or equal to another fact's id, binds nothing.
    """
    facts = tuple(facts)
    bound = {fact.fact_id: fact for fact in facts}
    owners: dict[str, list[Fact]] = {}
    for fact in facts:
        if fact.calculation_id is not None:
            owners.setdefault(fact.calculation_id, []).append(fact)
    for calculation_id, carriers in owners.items():
        if len(carriers) == 1 and bound.get(calculation_id, carriers[0]) is carriers[0]:
            bound[calculation_id] = carriers[0]
    return bound


def _fact_issues(run: Run, fact: "Fact") -> tuple[str, ...]:
    """Issues of one resolved reference: what kind of fact it may name, and its unit.

    A figure's unit token is a declared expectation, never display text: it must be the
    fact's own unit or the unit Python shows after the number (``report_view.figure_unit``).
    """
    # Imported here: contracts validates Claim.text with this module, so this module cannot
    # import report_view (which imports contracts) when it loads.
    from deploy_vii.report_view import figure_unit

    if run.figure:
        if fact.status != "known" or fact.amount is None:
            return (f"Figure reference needs a known numeric fact: {run.text}",)
        if not fact.citations and fact.calculation_id is None:
            return (f"Figure reference has no citation or calculation: {run.text}",)
        shown = figure_unit(fact)
        if run.unit is not None and run.unit not in {fact.unit, shown}:
            return (
                f"Unit {run.unit} differs from the fact's unit {shown or fact.unit}: {run.text}",
            )
    elif run.kind == "ref" and fact.amount is not None:
        return (f"A numeric fact needs a figure reference {{{run.text}|unit}}",)
    return ()


def issues(
    text: str, bound: Mapping[str, "Fact"], *, names: Collection[str] = ()
) -> tuple[str, ...]:
    """All issues of run text against one module's bound facts (``bind``), in reading order:
    syntax, labels, ids and the kind of fact each reference names."""
    gaps = {ref for ref, fact in bound.items() if fact.status != "known"}
    refs = bound.keys() - gaps
    try:
        runs = tokenize(text, gaps=gaps)
    except ValueError as error:
        return (str(error),)
    found: list[str] = []
    for run in runs:
        found += _run_issues(run, refs=refs, gaps=gaps, names=names)
        if run.kind != "text" and run.text in refs:
            found += _fact_issues(run, bound[run.text])
    return tuple(dict.fromkeys(found))


def prose_issues(module: "Module", *, names: Collection[str] = ()) -> tuple[str, ...]:
    """Module validation (MC-2): every claim resolves against the module's own facts."""
    bound = bind(module.facts)  # once per module: a module may carry many claims and facts
    return tuple(
        f"Claim {claim.claim_id}: {issue}"
        for claim in module.claims
        for issue in issues(claim.text, bound, names=names)
    )
