"""Python-owned display formatting (decision 0004 sections 4 and 5).

Values stay exact upstream; only the displayed string rounds, ROUND_HALF_UP on the exact
decimal. The HTML never spells ``null``: every non-known state has its own spelling and
fails closed when the data that spelling needs (gap id, reason, as-of date) is absent.
"""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, Inexact, InvalidOperation
from typing import Literal

UnitClass = Literal["amount", "multiple", "percent", "pp", "date", "text"]
CellState = Literal["known", "gap", "not_meaningful", "blocked", "not_evaluated", "stale"]

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_GAP_ID = re.compile(r"G\d+")
# Wide enough that quantize never raises InvalidOperation for any realistic magnitude.
_CONTEXT = Context(prec=120, rounding=ROUND_HALF_UP)
# Scaling must be exact: a value wider than the context would round before the display does.
_EXACT = Context(prec=120, traps=[InvalidOperation, Inexact])
# unit class -> (decimal places, scale applied before rounding, suffix)
_NUMERIC: dict[str, tuple[int, int, str]] = {
    "amount": (0, 1, ""),
    "multiple": (2, 1, "x"),
    "percent": (1, 100, "%"),
    "pp": (1, 1, "pp"),
}


def format_date(value: date) -> str:
    """``D Mon YYYY`` without locale dependence."""
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def _number(amount: Decimal, unit_class: str, decimals: int | None = None) -> str:
    places, scale, suffix = _NUMERIC[unit_class]
    if decimals is not None:
        places = decimals  # an explicit precision, e.g. a per-share amount's cents
    if not amount.is_finite():
        raise ValueError("Cannot display a non-finite number")
    try:
        # Scale in the wide context too: the default 28-digit context would round first.
        scaled = _EXACT.multiply(amount, Decimal(scale))
        rounded = scaled.quantize(Decimal(1).scaleb(-places), context=_CONTEXT)
    except (InvalidOperation, Inexact):
        raise ValueError("Number is too large to display exactly") from None
    # copy_abs, not abs(): abs() rounds to the default 28-digit context.
    body = f"{rounded.copy_abs():,.{places}f}"
    # A value that rounds to zero is shown unsigned, never as "(0)".
    shown = f"({body})" if rounded < 0 else body
    return shown + suffix


def _known(
    amount: Decimal | None,
    unit_class: str,
    as_of: date | None,
    text: str | None,
    decimals: int | None = None,
) -> str:
    if unit_class == "date":
        if as_of is None or amount is not None:
            raise ValueError("A date is displayed from as_of alone")
        return format_date(as_of)
    if unit_class == "text":
        if amount is not None or not text:
            raise ValueError("Text is displayed from non-empty text alone")
        return text
    if unit_class not in _NUMERIC:
        raise ValueError(f"Unknown unit class: {unit_class}")
    if amount is None:
        raise ValueError("A known numeric value requires an amount")
    return _number(amount, unit_class, decimals)


def _gap_id(gap_id: str | None) -> str:
    if gap_id is None or not _GAP_ID.fullmatch(gap_id):
        raise ValueError("A gap or not-meaningful cell requires a G# gap id")
    return gap_id


def format_value(
    amount: Decimal | None,
    unit_class: UnitClass,
    state: CellState,
    *,
    gap_id: str | None = None,
    reason: str | None = None,
    as_of: date | None = None,
    text: str | None = None,
    decimals: int | None = None,
) -> str:
    """Spell one cell. ``percent`` takes a decimal fraction, ``pp`` takes percentage points.

    ``as_of`` is the displayed date for the ``date`` class and the stamp for ``stale``.
    ``text`` carries the value of the ``text`` class. ``decimals`` overrides the class's
    decimal places for a numeric value (a fact declares it; nothing infers it from the unit).
    """
    if state == "known":
        return _known(amount, unit_class, as_of, text, decimals)
    if amount is not None and state != "stale":
        raise ValueError(f"A {state} cell cannot carry an amount")
    if state == "gap":
        return f"∅ {_gap_id(gap_id)}"
    if state == "not_meaningful":
        return f"∅ {_gap_id(gap_id)} n.m."
    if state == "blocked":
        return "—"
    if state == "not_evaluated":
        if not reason:
            raise ValueError("A not-evaluated cell requires a reason")
        return f"Not evaluated: {reason}"
    if state == "stale":
        if as_of is None or unit_class == "date":
            raise ValueError("A stale value requires an as-of stamp and a non-date value")
        return f"⏱ {_known(amount, unit_class, None, text, decimals)} as of {format_date(as_of)}"
    raise ValueError(f"Unknown cell state: {state}")
