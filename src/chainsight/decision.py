"""Turn a probability and a known order value into one ranked action.

A probability is not a decision. An order at 90% risk carrying a rupee of margin and one at
85% risk carrying sixty are the same number to a classifier and different problems to the
person who has to act, and a control tower that flags both as HIGH has not helped anybody.

Three things are kept deliberately separate here:

**The model** says how likely a late delivery is. It knows nothing about money.

**The cost model** says what a late delivery costs and what intervening costs. Every number
in it is an assumption, none of it is learned from the data, and `docs/decision_engine.md`
argues each one. It is a `dataclass` so an admin can change it without touching this file.

**The engine** combines them. It is arithmetic, it is deterministic, and it is tested
separately from the model, because a bug here does not crash -- it produces a confidently
wrong ranking.

The margin half comes from a measurement rather than a model, and that is not a shortcut.
`docs/results.md` establishes that `Order Item Profit Ratio` cannot be predicted from
at-order features by anything: a predictor allowed to cheat reaches R-squared 0.0036. So
expected profit is the measured mean margin times the order total, which is known exactly
when the order is placed. The number is an estimate with a stated basis rather than a model
output dressed up as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: The mean margin ratio on the training slice. Multiplying it by a known order total is
#: the whole of the profit estimate, because `docs/results.md` establishes that nothing can
#: predict the ratio itself.
TRAINING_MEAN_MARGIN = 0.1196

#: The mean `Order Item Total` on the training slice. This is a retail table: orders run
#: from a few rupees to 499.95, and the average order carries about 21 of margin. Every
#: default below is scaled to that, and the numbers in an earlier draft of this project --
#: interventions costing 200 against orders worth 50,000 -- described a different business
#: entirely. Measuring first is what caught it.
TRAINING_MEAN_ORDER_VALUE = 176.88


class Priority(Enum):
    """What the operator should do, ordered by how much doing it is worth."""

    CRITICAL = "critical"
    HIGH = "high"
    MONITOR = "monitor"
    LOW = "low"


@dataclass(frozen=True)
class CostModel:
    """What a late delivery costs, and what preventing one costs.

    None of this is learned. The dataset records no intervention, no penalty and no
    customer response, so every field is a business assumption that a real deployment would
    replace with its own figures. They are here as named, editable numbers rather than
    constants buried in a formula, so that changing them is a configuration change and
    disagreeing with them is a conversation about the business rather than about the code.
    """

    #: What it costs to act on one order: expedite it, call the carrier, warn the customer.
    #: Small, because the average order it would be spent on is worth 176.88.
    intervention: float = 15.0

    #: The share of an order's margin assumed lost when it arrives late.
    margin_lost_when_late: float = 0.5

    #: Goodwill and support cost that does not scale with order size: a support contact,
    #: a discount on the next order, some chance of losing the customer.
    fixed_penalty_when_late: float = 25.0

    #: The mean margin ratio used to turn an order total into an expected profit.
    mean_margin: float = TRAINING_MEAN_MARGIN

    #: The order the single global threshold is calibrated against. Per-order economics are
    #: handled by `net_benefit`, which does not use the threshold at all; the threshold
    #: exists for the risk label an operator reads at a glance.
    typical_order_value: float = TRAINING_MEAN_ORDER_VALUE

    #: Net benefit above which an order is CRITICAL, then HIGH, then MONITOR. The largest
    #: order in the table exposes about 55, so a band above that would never be reached.
    critical_above: float = 25.0
    high_above: float = 10.0
    monitor_above: float = 0.0

    def __post_init__(self) -> None:
        if self.intervention <= 0:
            raise ValueError("intervention must cost something, or every order is worth acting on")
        if not 0.0 <= self.margin_lost_when_late <= 1.0:
            raise ValueError("margin_lost_when_late is a share, so it belongs in [0, 1]")
        if not self.critical_above > self.high_above > self.monitor_above:
            raise ValueError("the priority bands must descend: critical > high > monitor")

    @property
    def threshold(self) -> float:
        """The probability above which intervening is worth it on an average order.

        The standard cost-sensitive rule. Acting on an order that would have arrived on time
        wastes `intervention`; failing to act on one that arrives late costs
        `late_cost_of_an_average_order`. Setting the two expected costs equal gives

            p* = intervention / (intervention + cost of a late delivery)

        which on the default numbers is about 0.30 -- well below 0.5. That is the point of
        deriving it: a threshold of 0.5 silently assumes the two mistakes cost the same, and
        here a missed late delivery costs a little over twice an unnecessary intervention.
        """
        late_cost = self.late_cost(self.typical_order_value)
        return self.intervention / (self.intervention + late_cost)

    def expected_profit(self, order_total: float) -> float:
        """Measured mean margin times a known order total. Not a prediction."""
        return self.mean_margin * order_total

    def late_cost(self, order_total: float) -> float:
        """What one late delivery on this order is assumed to cost."""
        margin_at_risk = self.expected_profit(order_total) * self.margin_lost_when_late
        return margin_at_risk + self.fixed_penalty_when_late


@dataclass(frozen=True)
class Decision:
    """Everything the operator's report shows about one order."""

    probability: float
    order_total: float
    expected_profit: float
    value_at_risk: float
    net_benefit: float
    priority: Priority
    threshold: float
    recommendation: str

    @property
    def is_flagged(self) -> bool:
        return self.probability >= self.threshold


def decide(probability: float, order_total: float, costs: CostModel | None = None) -> Decision:
    """Combine a late-delivery probability with a known order value.

    `value_at_risk` is what the lateness is expected to cost; `net_benefit` subtracts what
    acting would cost. Ranking on net benefit rather than on probability is the entire
    reason this module exists: on the default costs it puts an 85%-risk order at the top of
    the catalogue's price range above a 90%-risk order worth twenty, because the first
    exposes 46.66 and the second 23.55.

    The gap is narrower than it would be in a business with a wider price range. Every order
    in this table falls between a few rupees and 499.95, so the fixed goodwill penalty is
    the larger half of the exposure on a typical order, and value ranking can only do so
    much. That is a property of the data; it belongs in the model card rather than being
    hidden by inventing a bigger spread.
    """
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"a probability belongs in [0, 1], not {probability}")
    if order_total < 0:
        raise ValueError(f"an order total cannot be negative, and this one is {order_total}")

    costs = costs or CostModel()
    expected_profit = costs.expected_profit(order_total)
    value_at_risk = probability * costs.late_cost(order_total)
    net_benefit = value_at_risk - costs.intervention

    priority = _priority(net_benefit, costs)
    return Decision(
        probability=probability,
        order_total=order_total,
        expected_profit=expected_profit,
        value_at_risk=value_at_risk,
        net_benefit=net_benefit,
        priority=priority,
        threshold=costs.threshold,
        recommendation=_recommendation(priority, probability, costs),
    )


def _priority(net_benefit: float, costs: CostModel) -> Priority:
    if net_benefit > costs.critical_above:
        return Priority.CRITICAL
    if net_benefit > costs.high_above:
        return Priority.HIGH
    if net_benefit > costs.monitor_above:
        return Priority.MONITOR
    return Priority.LOW


def _recommendation(priority: Priority, probability: float, costs: CostModel) -> str:
    """One sentence an operator can act on, naming the reason rather than the number."""
    risk = f"{probability:.0%}"
    if priority is Priority.CRITICAL:
        return f"Expedite now. {risk} risk on an order large enough to justify the cost."
    if priority is Priority.HIGH:
        return f"Worth intervening. {risk} risk, and acting costs less than the exposure."
    if priority is Priority.MONITOR:
        return (
            f"Watch it. {risk} risk, but the exposure barely covers "
            f"the {costs.intervention:.0f} it would cost to act."
        )
    return f"Leave it. At {risk} risk this order is not worth the cost of intervening."
