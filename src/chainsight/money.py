"""What the numbers in this project are denominated in, and how they are written down.

The dataset never names its currency, so this module names it. Every one of the 180,519
rows belongs to a customer in `EE. UU.` or Puerto Rico, both of which are on the dollar,
and no product is ever sold at two prices: the Perfect Fitness Rip Deck is 59.99 into all
150 countries it reaches. A per-destination currency would need a different figure for
France, and the table simply does not hold one. These are one seller's books in dollars,
and leaving the figures bare was what let nine sentences of prose call them rupees.

It is a setting rather than a constant because two different kinds of money reach the
screen. Order totals come out of the dataset and are dollars permanently. The cost model on
`/admin/costs` -- what stepping in costs, what a late delivery costs in goodwill -- is typed
in by whoever runs the application, in whatever currency their business runs on. A `$`
hard-coded into the templates would put a dollar sign on a number somebody entered in
rupees, which is a worse failure than no sign at all.

Only currencies with a two-decimal minor unit are accepted. The formatter writes cents
unconditionally, and `JPY 1,234.56` is not a yen amount because the yen has no subunit.
A whitelist that refuses at startup beats a fallback that prints a wrong number on every
page, so an unsupported code stops the process rather than the reader.

One consequence worth knowing: the non-ASCII symbols reach a Windows console through
whatever encoding it is set to, and a legacy code page cannot render `₹`. The default is
ASCII and unaffected; an operator who selects one of the others and runs the CLI on such a
console will want `PYTHONUTF8=1`.
"""

from __future__ import annotations

import os

#: The environment variable that selects the display currency, read by both the CLI and
#: `chainsight_web.config`, so the two cannot drift into different answers.
CURRENCY_VAR = "CHAINSIGHT_CURRENCY"

#: The dataset's own currency, and the one every default in `decision.CostModel` was
#: calibrated against.
DEFAULT_CURRENCY = "USD"

#: Code to symbol. Every entry has a two-decimal minor unit, which is the assumption
#: `format_money` makes and the reason this is a whitelist. The symbol goes in front in
#: every case, the euro included: one rule that is occasionally not the local convention is
#: worth more than a placement table nobody would maintain.
SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "INR": "₹",
    "CAD": "CA$",
    "AUD": "A$",
}

#: Named in the refusal rather than left to be guessed at. These are real currencies whose
#: minor unit is not two decimals, so the problem is the formatter, not the code being
#: unrecognised, and the message should say which.
_NO_MINOR_UNIT = ("JPY", "KRW", "CLP", "ISK", "VND")


class CurrencyError(ValueError):
    """A currency this project cannot write down without getting it wrong."""


def symbol_for(currency: str) -> str:
    """The prefix for this currency, or a refusal naming what is supported."""
    try:
        return SYMBOLS[currency]
    except KeyError:
        raise CurrencyError(_refusal(currency)) from None


def format_money(amount: float, currency: str = DEFAULT_CURRENCY) -> str:
    """An amount as an operator reads it: `$1,234.50`, and `-$3.20` when it is negative.

    The sign goes outside the symbol because `$-3.20` reads as a typo, and `net_benefit`
    is below zero often enough for it to matter -- that is the whole meaning of an order
    that costs more to rescue than it is worth.

    Rounding happens before the sign is chosen, so an amount that is negative only in the
    third decimal prints as `$0.00` rather than `-$0.00`.
    """
    symbol = symbol_for(currency)
    rounded = round(float(amount), 2)
    sign = "-" if rounded < 0 else ""
    return f"{sign}{symbol}{abs(rounded):,.2f}"


def resolve_currency(environ: dict[str, str] | None = None) -> str:
    """The configured currency, defaulting to the dollar the dataset is priced in."""
    source = dict(os.environ if environ is None else environ)
    requested = source.get(CURRENCY_VAR, DEFAULT_CURRENCY).strip().upper()
    if requested not in SYMBOLS:
        raise CurrencyError(_refusal(requested))
    return requested


def _refusal(currency: str) -> str:
    supported = ", ".join(sorted(SYMBOLS))
    if currency in _NO_MINOR_UNIT:
        return (
            f"{currency} has no two-decimal minor unit, and this formatter writes cents on "
            f"every amount. Printing {currency} here would show a figure that does not "
            f"exist. Supported: {supported}."
        )
    return f"{currency!r} is not a currency this project can write down. Supported: {supported}."
