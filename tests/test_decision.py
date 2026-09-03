"""The decision engine is arithmetic, and a bug in it does not crash.

It produces a confidently wrong ranking instead, which nothing downstream would catch, so
this file tests the behaviour an operator would notice rather than the formulas.

Every figure here comes from the dataset's real range. This is a retail table: orders run
from a few dollars to $499.95 and the average carries about $21 of margin. An earlier draft
of this project reasoned about interventions costing $200 against orders worth $50,000, which
described a different business entirely.
"""

from __future__ import annotations

import pytest

from chainsight.decision import CostModel, Decision, Priority, decide

LARGEST_ORDER = 499.95
TYPICAL_ORDER = 176.88
SMALL_ORDER = 20.0


class TestCostModel:
    def test_the_default_threshold_is_below_a_half(self) -> None:
        """A threshold of 0.5 assumes the two mistakes cost the same. Here they do not."""
        assert CostModel().threshold < 0.5

    def test_the_threshold_is_the_break_even_probability_it_claims_to_be(self) -> None:
        """The flag and the ranking have to be kept on the same books.

        `net_benefit` charges the intervention whatever the outcome, so the probability at
        which acting stops being a loss is `intervention / (effectiveness x late cost)`.
        Deriving the threshold any other way -- this project used
        `intervention / (intervention + late cost)` -- flags orders that the ranking then
        calls LOW, and an operator is left holding two answers to one question.
        """
        costs = CostModel()

        break_even = costs.intervention / (
            costs.intervention_effectiveness * costs.late_cost(costs.typical_order_value)
        )

        assert costs.threshold == pytest.approx(break_even)

    def test_a_less_effective_intervention_raises_the_threshold(self) -> None:
        """Acting that prevents less of the damage has to clear a higher bar to be worth it."""
        assert CostModel(intervention_effectiveness=0.5).threshold > CostModel().threshold

    def test_an_effectiveness_outside_its_range_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r"\(0, 1\]"):
            CostModel(intervention_effectiveness=0.0)

    def test_an_intervention_that_can_never_repay_itself_flags_nothing(self) -> None:
        """A cut-off above 100% is not a sentence any interface can render, so it clamps."""
        assert CostModel(intervention=10_000.0).threshold == 1.0

    def test_making_intervention_cheaper_lowers_the_threshold(self) -> None:
        expensive = CostModel(intervention=1000.0)
        cheap = CostModel(intervention=1.0)

        assert cheap.threshold < expensive.threshold

    def test_making_lateness_more_costly_lowers_the_threshold(self) -> None:
        mild = CostModel(fixed_penalty_when_late=1.0)
        severe = CostModel(fixed_penalty_when_late=5000.0)

        assert severe.threshold < mild.threshold

    def test_free_intervention_is_refused_rather_than_flagging_everything(self) -> None:
        with pytest.raises(ValueError, match="cost something"):
            CostModel(intervention=0.0)

    def test_a_share_outside_zero_to_one_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            CostModel(margin_lost_when_late=1.5)

    def test_bands_that_do_not_descend_are_refused(self) -> None:
        """Otherwise a band becomes unreachable and orders silently skip a priority."""
        with pytest.raises(ValueError, match="descend"):
            CostModel(critical_above=10.0, high_above=50.0)

    def test_expected_profit_is_the_measured_mean_margin_times_a_known_total(self) -> None:
        costs = CostModel(mean_margin=0.2)

        assert costs.expected_profit(1000.0) == pytest.approx(200.0)

    def test_a_typical_order_can_never_reach_critical_however_risky_it_is(self) -> None:
        """Deliberate, and a consequence of the narrow price range rather than a bug.

        A 176.88 order exposes at most 35.60, so its best possible net benefit is 20.60 and
        the CRITICAL band starts at 25. Only the upper end of the catalogue can be critical,
        which is what a value-aware priority is supposed to mean.
        """
        certain = decide(probability=1.0, order_total=TYPICAL_ORDER)

        assert certain.priority is Priority.HIGH

    def test_the_fixed_penalty_is_the_larger_half_of_a_typical_exposure(self) -> None:
        """A property of this table worth knowing before reading any ranking.

        Every order is under 500, so the margin at risk on a typical one is about 10 against
        a 25 goodwill penalty that does not scale with order size. Value ranking therefore
        does less work here than it would in a business with a wider price range, and the
        model card says so rather than the UI implying otherwise.
        """
        costs = CostModel()

        margin_at_risk = costs.expected_profit(TYPICAL_ORDER) * costs.margin_lost_when_late

        assert margin_at_risk < costs.fixed_penalty_when_late


class TestDecide:
    def test_a_valuable_order_at_high_risk_is_critical(self) -> None:
        decision = decide(probability=0.85, order_total=LARGEST_ORDER)

        assert decision.priority is Priority.CRITICAL

    def test_a_riskier_cheap_order_ranks_below_a_valuable_one(self) -> None:
        """The whole reason the engine exists, in one comparison."""
        cheap = decide(probability=0.90, order_total=SMALL_ORDER)
        valuable = decide(probability=0.85, order_total=LARGEST_ORDER)

        assert cheap.probability > valuable.probability
        assert valuable.net_benefit > cheap.net_benefit
        assert cheap.priority is not Priority.CRITICAL

    def test_ranking_is_by_net_benefit_not_by_probability(self) -> None:
        riskier = decide(probability=0.95, order_total=SMALL_ORDER)
        richer = decide(probability=0.80, order_total=LARGEST_ORDER)

        assert richer.probability < riskier.probability
        assert richer.net_benefit > riskier.net_benefit

    def test_an_order_at_no_risk_carries_no_value_at_risk(self) -> None:
        decision = decide(probability=0.0, order_total=LARGEST_ORDER)

        assert decision.value_at_risk == 0.0
        assert decision.priority is Priority.LOW

    def test_acting_is_never_worth_it_when_the_exposure_is_below_its_cost(self) -> None:
        costs = CostModel(intervention=10_000.0)

        decision = decide(probability=0.99, order_total=LARGEST_ORDER, costs=costs)

        assert decision.net_benefit < 0
        assert decision.priority is Priority.LOW

    def test_value_at_risk_scales_with_probability(self) -> None:
        low = decide(probability=0.2, order_total=TYPICAL_ORDER)
        high = decide(probability=0.8, order_total=TYPICAL_ORDER)

        assert high.value_at_risk == pytest.approx(4 * low.value_at_risk)

    def test_flagging_uses_the_derived_threshold_rather_than_a_half(self) -> None:
        """0.45 sits below 0.5 and above the derived 0.4216, so the two disagree here.

        This is the case that makes deriving the threshold worth the trouble: at 0.5 this
        order is ignored, and on the default costs ignoring it is the wrong call.
        """
        decision = decide(probability=0.45, order_total=TYPICAL_ORDER)

        assert decision.probability < 0.5
        assert decision.is_flagged

    def test_the_flag_and_the_ranking_agree_on_an_order_of_typical_value(self) -> None:
        """The threshold is calibrated on this order, so on this order they cannot disagree."""
        above = decide(probability=0.43, order_total=TYPICAL_ORDER)
        below = decide(probability=0.41, order_total=TYPICAL_ORDER)

        assert above.is_flagged and above.is_worth_acting_on
        assert not below.is_flagged and not below.is_worth_acting_on

    def test_a_flagged_cheap_order_can_still_not_be_worth_acting_on(self) -> None:
        """The divergence that survives, and the one the report has to name rather than hide.

        One threshold serves a catalogue of many prices. A cheaper order has less to lose,
        so it needs more risk before the same intervention repays itself, and `break_even`
        is the number that says so on that order's own report.
        """
        decision = decide(probability=0.50, order_total=SMALL_ORDER)

        assert decision.is_flagged
        assert not decision.is_worth_acting_on
        assert decision.break_even > decision.threshold

    def test_a_less_effective_intervention_shrinks_the_saving(self) -> None:
        certain = decide(0.8, TYPICAL_ORDER, CostModel())
        halved = decide(0.8, TYPICAL_ORDER, CostModel(intervention_effectiveness=0.5))

        assert halved.net_benefit < certain.net_benefit
        assert halved.value_at_risk == pytest.approx(certain.value_at_risk)

    def test_a_probability_outside_zero_to_one_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            decide(probability=1.4, order_total=TYPICAL_ORDER)

    def test_a_negative_order_total_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            decide(probability=0.5, order_total=-1.0)

    def test_a_zero_value_order_is_allowed(self) -> None:
        """Fully discounted orders exist in this table; refusing them would refuse real rows."""
        decision = decide(probability=0.9, order_total=0.0)

        assert decision.expected_profit == 0.0
        assert decision.priority is not Priority.CRITICAL


class TestRecommendation:
    @pytest.mark.parametrize(
        ("probability", "total", "expected"),
        [
            (0.85, LARGEST_ORDER, Priority.CRITICAL),
            (0.85, TYPICAL_ORDER, Priority.HIGH),
            (0.60, TYPICAL_ORDER, Priority.MONITOR),
            (0.10, SMALL_ORDER, Priority.LOW),
        ],
    )
    def test_every_priority_produces_an_actionable_sentence(
        self, probability: float, total: float, expected: Priority
    ) -> None:
        decision = decide(probability=probability, order_total=total)

        assert decision.priority is expected
        assert decision.recommendation.endswith(".")
        assert len(decision.recommendation.split()) > 4

    def test_the_sentence_names_the_risk_the_operator_is_being_asked_about(self) -> None:
        decision = decide(probability=0.85, order_total=LARGEST_ORDER)

        assert "85%" in decision.recommendation


def test_a_decision_carries_everything_the_report_needs_to_show() -> None:
    """The UI renders this object directly, so a missing field is a missing panel."""
    decision = decide(probability=0.7, order_total=TYPICAL_ORDER)

    assert isinstance(decision, Decision)
    for value in (
        decision.probability,
        decision.order_total,
        decision.expected_profit,
        decision.value_at_risk,
        decision.net_benefit,
        decision.threshold,
        decision.break_even,
    ):
        assert isinstance(value, float)
    assert decision.priority in Priority
    assert decision.recommendation
