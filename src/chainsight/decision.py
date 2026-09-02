"""Turn a probability and a known order value into one ranked action.

A probability is not a decision. An order at 90% risk carrying a rupee of margin and one at
85% risk carrying sixty are the same number to a classifier and different problems to the
person who has to act, and a control tower that flags both as HIGH has not helped anybody.

Three things are kept deliberately separate here:

**The model** says how likely a late delivery is. It knows nothing about money.

**The cost model** says what a late delivery costs, what intervening costs, and how much of
the damage intervening actually prevents. Every number in it is an assumption, none of it is
learned from the data, and `docs/decision_engine.md` argues each one. It is a `dataclass` so
an admin can change it without touching this file.

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

    #: The share of the damage an intervention is assumed to prevent. 1.0 says expediting
    #: always works, which is optimistic and almost certainly wrong -- but it is the
    #: assumption this engine made silently before the field existed, and inventing a
    #: smaller number would assert something about a business this dataset does not record.
    #: It is here to be lowered by whoever has the carrier data to lower it with. Lowering
    #: it raises the threshold and shrinks every net benefit; below about 0.75 the largest
    #: order in this catalogue can no longer reach CRITICAL, so the bands need rescaling
    #: with it. `docs/decision_engine.md` shows the sensitivity.
    intervention_effectiveness: float = 1.0

    #: The share of an order's margin assumed lost when it arrives late.
    margin_lost_when_late: float = 0.5

    #: Goodwill and support cost that does not scale with order size: a support contact,
    #: a discount on the next order, some chance of losing the customer.
    fixed_penalty_when_late: float = 25.0

    #: The mean margin ratio used to turn an order total into an expected profit.
    mean_margin: float = TRAINING_MEAN_MARGIN

    #: The order the single global threshold is calibrated against. Per-order economics are
    #: handled by `net_benefit`, which does not use the threshold at all, and by
    #: `Decision.break_even`, which is the same sum done with the order's own value. The
    #: threshold exists for the risk label an operator reads at a glance.
    typical_order_value: float = TRAINING_MEAN_ORDER_VALUE

    #: Net benefit above which an order is CRITICAL, then HIGH, then MONITOR. The largest
    #: order in the table exposes about 55, so a band above that would never be reached.
    critical_above: float = 25.0
    high_above: float = 10.0
    monitor_above: float = 0.0

    def __post_init__(self) -> None:
        if self.intervention <= 0:
            raise ValueError("intervention must cost something, or every order is worth acting on")
        if not 0.0 < self.intervention_effectiveness <= 1.0:
            raise ValueError(
                "intervention_effectiveness is the share of the damage acting prevents, so it "
                "belongs in (0, 1]. At zero nothing is ever worth doing and the threshold is "
                "undefined."
            )
        if not 0.0 <= self.margin_lost_when_late <= 1.0:
            raise ValueError("margin_lost_when_late is a share, so it belongs in [0, 1]")
        if not self.critical_above > self.high_above > self.monitor_above:
            raise ValueError("the priority bands must descend: critical > high > monitor")

    @property
    def threshold(self) -> float:
        """The probability above which intervening pays on an order of typical value.

        Not acting costs `p x late_cost`. Acting costs `intervention`, plus whatever the
        intervention fails to prevent, `(1 - effectiveness) x p x late_cost`. Setting the two
        equal gives

            p* = intervention / (effectiveness x cost of a late delivery)

        which on the default numbers is 0.4216. Still below 0.5 -- a missed late delivery
        costs more than an unnecessary intervention, and deriving that rather than rounding
        at half is the whole point -- but not as far below as the
        `intervention / (intervention + late cost)` this project used until the two halves of
        its own arithmetic were checked against each other. That form is Elkan's
        false-positive rule, and it holds only when acting on an order that really was going
        to be late is free. Here it is not: `net_benefit` subtracts the intervention whatever
        the outcome. A threshold kept on different books from the ranking is a threshold that
        contradicts it, and it did -- orders between 0.2966 and 0.4216 were flagged as needing
        attention and ranked LOW, which reads "leave it", on the same screen.

        One number calibrated on `typical_order_value` cannot be right for every order in a
        catalogue. A cheaper order needs more risk before acting pays and a dearer one needs
        less; `Decision.break_even` is this same sum done with the order's own value.
        """
        return _break_even(self, self.typical_order_value)

    def expected_profit(self, order_total: float) -> float:
        """Measured mean margin times a known order total. Not a prediction."""
        return self.mean_margin * order_total

    def late_cost(self, order_total: float) -> float:
        """What one late delivery on this order is assumed to cost."""
        margin_at_risk = self.expected_profit(order_total) * self.margin_lost_when_late
        return margin_at_risk + self.fixed_penalty_when_late


def _break_even(costs: CostModel, order_total: float) -> float:
    """The probability at which acting on an order of this size stops being a loss.

    Clamped at 1. When an intervention cannot recover its own cost the honest answer is that
    no probability justifies it, and "we flag anything above 140%" is not a sentence an
    interface can render.
    """
    recoverable = costs.intervention_effectiveness * costs.late_cost(order_total)
    return min(1.0, costs.intervention / recoverable)


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
    #: The break-even probability for this order's own value, which is what `net_benefit` is
    #: judged against. It differs from `threshold` for every order not worth
    #: `typical_order_value`, and the report says so rather than leaving an operator to
    #: reconcile a flag against a priority that disagrees with it.
    break_even: float
    recommendation: str

    @property
    def is_flagged(self) -> bool:
        """Above the catalogue-wide risk cut-off. A risk label, not an instruction.

        `is_worth_acting_on` is the instruction. The two agree on an order of typical value
        and diverge either side of it, which is what one global cut-off costs.
        """
        return self.probability >= self.threshold

    @property
    def is_worth_acting_on(self) -> bool:
        """Whether stepping in is expected to save more than it costs on this order."""
        return self.net_benefit > 0


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
    net_benefit = costs.intervention_effectiveness * value_at_risk - costs.intervention

    priority = _priority(net_benefit, costs)
    return Decision(
        probability=probability,
        order_total=order_total,
        expected_profit=expected_profit,
        value_at_risk=value_at_risk,
        net_benefit=net_benefit,
        priority=priority,
        threshold=costs.threshold,
        break_even=_break_even(costs, order_total),
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
        return (
            f"Act on this now. {risk} chance of arriving late, on an order big enough that "
            "sorting it out pays for itself several times over."
        )
    if priority is Priority.HIGH:
        return (
            f"Worth stepping in. {risk} chance of arriving late, and sorting it out costs "
            "less than letting it happen."
        )
    if priority is Priority.MONITOR:
        return (
            f"Keep an eye on it. {risk} chance of arriving late, but you would barely cover "
            f"the {costs.intervention:.0f} it costs to step in."
        )
    return (
        f"Leave this one. At a {risk} chance of arriving late, stepping in would cost more "
        "than it saves."
    )
