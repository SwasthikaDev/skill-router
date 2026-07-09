"""Fill endpoint placeholders from the agent's need.

Registry endpoints often look like
    https://api.example.com/latest?amount={amount}&from={from}&to={to}
When the need already contains the values ("convert 100 USD to EUR"), we can fill
those in so the returned call is runnable as-is instead of a template the agent has
to complete. If we can't confidently fill a placeholder we leave it and say so, so
nothing is ever silently wrong.
"""
from __future__ import annotations

import re

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_CCY = re.compile(r"\b[A-Za-z]{3}\b")

# Common ISO currency codes, used to tell a real code (USD) from a stray word (the).
_KNOWN_CCY = {
    "usd", "eur", "gbp", "jpy", "inr", "aud", "cad", "chf", "cny", "sgd",
    "hkd", "nzd", "sek", "nok", "dkk", "zar", "brl", "mxn", "aed", "krw",
}

_FROM_KEYS = {"from", "base", "source", "src"}
_TO_KEYS = {"to", "target", "dest", "symbols", "symbol"}
_AMOUNT_KEYS = {"amount", "value", "qty", "quantity", "amt"}


def _currencies(need: str) -> list[str]:
    out = []
    for m in _CCY.finditer(need):
        tok = m.group(0)
        if tok.lower() in _KNOWN_CCY:
            out.append(tok.upper())
    return out


def _directional_currencies(need: str) -> tuple[str | None, str | None]:
    """Decide (from, to) from the phrasing, not just left-to-right order.

    The currency next to the amount is the source; the currency after a
    ``to``/``into``/``in`` marker is the target. So "how many USD is 100 EUR"
    correctly reads as from=EUR, to=USD instead of the reversed from=USD.
    Falls back to positional order when there is no directional cue.
    """
    ccys = _currencies(need)
    if len(ccys) < 2:
        return (ccys[0] if ccys else None, None)
    known = {c.upper() for c in ccys}
    low = need.lower()
    from_ccy = to_ccy = None
    m = re.search(r"\b\d+(?:\.\d+)?\s*([a-z]{3})\b", low)  # amount-adjacent = source
    if m and m.group(1).upper() in known:
        from_ccy = m.group(1).upper()
    m2 = re.search(r"\b(?:to|into|in)\s+([a-z]{3})\b", low)  # after to/into/in = target
    if m2 and m2.group(1).upper() in known and m2.group(1).upper() != from_ccy:
        to_ccy = m2.group(1).upper()
    if from_ccy and not to_ccy:
        to_ccy = next((c for c in ccys if c != from_ccy), None)
    elif to_ccy and not from_ccy:
        from_ccy = next((c for c in ccys if c != to_ccy), None)
    elif not from_ccy and not to_ccy:
        from_ccy, to_ccy = ccys[0], ccys[1]
    return from_ccy, to_ccy


def fill_url(need: str, url: str) -> tuple[str, bool, list[str]]:
    """Return (url, fully_filled, unfilled_placeholders)."""
    names = _PLACEHOLDER.findall(url)
    if not names:
        return url, True, []

    numbers = _NUMBER.findall(need)
    from_ccy, to_ccy = _directional_currencies(need)

    filled = url
    missing: list[str] = []
    for name in names:
        low = name.lower()
        value = None
        if low in _AMOUNT_KEYS and numbers:
            value = numbers[0]
        elif low in _FROM_KEYS and from_ccy:
            value = from_ccy
        elif low in _TO_KEYS and to_ccy:
            value = to_ccy
        elif low in {"currency", "ccy"} and from_ccy:
            value = from_ccy

        if value is None:
            missing.append(name)
        else:
            filled = filled.replace("{" + name + "}", value)

    return filled, (len(missing) == 0), missing
