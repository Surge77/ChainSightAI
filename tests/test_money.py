"""What the money on screen says, and what it refuses to say.

The dataset is denominated in dollars and the code used to leave every figure bare, which
made `499.95` a number with no unit and let nine sentences of prose call it rupees. These
tests pin the label on. They also pin the refusals: a currency whose minor unit is not two
decimals cannot be written by this formatter, and printing it anyway would be a wrong
number rather than a missing one.
"""

from __future__ import annotations

import pytest

from chainsight.money import (
    CURRENCY_VAR,
    DEFAULT_CURRENCY,
    SYMBOLS,
    CurrencyError,
    format_money,
    resolve_currency,
    symbol_for,
)


class TestDefault:
    def test_the_default_is_the_dollar_the_dataset_is_priced_in(self) -> None:
        assert DEFAULT_CURRENCY == "USD"

    def test_formats_in_dollars_without_being_asked(self) -> None:
        assert format_money(1234.5) == "$1,234.50"

    def test_groups_thousands_so_a_large_figure_can_be_read_at_a_glance(self) -> None:
        assert format_money(1234567.891) == "$1,234,567.89"

    def test_the_largest_order_in_this_table(self) -> None:
        assert format_money(499.95) == "$499.95"


class TestSign:
    """`net_benefit` goes below zero, and the report says out loud that it can."""

    def test_the_minus_sign_goes_outside_the_symbol(self) -> None:
        assert format_money(-3.2) == "-$3.20"

    def test_an_amount_that_rounds_to_nothing_is_not_negative_nothing(self) -> None:
        assert format_money(-0.001) == "$0.00"

    def test_zero(self) -> None:
        assert format_money(0.0) == "$0.00"


class TestOtherCurrencies:
    """The cost model is typed in by an operator, who may not be billing in dollars."""

    def test_a_supported_currency_uses_its_own_symbol(self) -> None:
        assert format_money(12.0, "EUR") == "€12.00"
        assert format_money(12.0, "INR") == "₹12.00"

    def test_symbol_for_returns_the_prefix(self) -> None:
        assert symbol_for("GBP") == "£"

    def test_every_symbol_in_the_table_is_usable(self) -> None:
        for code in SYMBOLS:
            assert format_money(1.0, code).endswith("1.00")


class TestRefusals:
    def test_a_currency_without_a_two_decimal_minor_unit_is_refused(self) -> None:
        # The formatter writes cents unconditionally, and the yen has none. Refusing is the
        # difference between no answer and a wrong one.
        with pytest.raises(CurrencyError, match="JPY"):
            symbol_for("JPY")

    def test_the_refusal_names_what_is_supported(self) -> None:
        with pytest.raises(CurrencyError, match="USD"):
            symbol_for("ZZZ")

    def test_an_empty_currency_is_not_silently_the_default(self) -> None:
        with pytest.raises(CurrencyError):
            symbol_for("")


class TestFromEnvironment:
    def test_absent_means_dollars(self) -> None:
        assert resolve_currency({}) == "USD"

    def test_reads_the_variable(self) -> None:
        assert resolve_currency({CURRENCY_VAR: "GBP"}) == "GBP"

    def test_case_and_spacing_are_not_a_configuration_error(self) -> None:
        assert resolve_currency({CURRENCY_VAR: " eur "}) == "EUR"

    def test_an_unsupported_code_stops_here_rather_than_at_the_first_price(self) -> None:
        with pytest.raises(CurrencyError):
            resolve_currency({CURRENCY_VAR: "JPY"})
