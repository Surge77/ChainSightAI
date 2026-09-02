"""The numbers the control tower shows, and the count beside every one of them.

Two rules, both learned the hard way elsewhere in this project.

**Every average carries its sample size.** A mean predicted risk of 0.81 over four orders
is not a finding, and a dashboard that renders it at the same size as one over four thousand
has told the reader something false without stating anything untrue. `Grouped.orders` is
never optional and the templates never drop it.

**The exposure adds up.** Money at risk splits exactly three ways -- what acting is
expected to recover, what acting costs, and what is left on orders where acting would cost
more than it saves. An earlier dashboard showed the first of those beside the total and let
the reader assume the difference was the second, which quietly hid the third.

**These are predicted risks on entered orders, not observed late rates.** The distinction
matters because the observed spread on this dataset is small: regional late rate varies by
about five points around a 0.5483 base rate, and an earlier draft of this project imagined
regions at 72%, 48% and 34%. Nothing here is allowed to imply that shape. The charts plot
what the model said, they are labelled as such, and the axis starts at zero so a
five-point spread looks like a five-point spread.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from chainsight_web.tables import Order, Prediction

#: Below this many orders a group's mean is noise, and the page says so rather than
#: rendering it as though it were a measurement.
NOISY_BELOW = 5


@dataclass(frozen=True)
class Grouped:
    """One bar of a chart: the label, the mean predicted risk, and how many orders it is."""

    label: str
    mean_probability: float
    orders: int

    @property
    def is_noisy(self) -> bool:
        return self.orders < NOISY_BELOW


@dataclass(frozen=True)
class Summary:
    """The whole dashboard, computed in one place so a template never does arithmetic."""

    orders: int
    scored: int
    flagged: int
    value_at_risk: float
    net_benefit_available: float
    #: How many orders repay the cost of stepping in. Not the same as `flagged`, and the
    #: dashboard says which of the two is an instruction.
    actionable: int
    #: What stepping in on those orders costs -- and, when an admin has set intervention
    #: effectiveness below 1, what stepping in is not expected to recover. Derived from the
    #: stored figures rather than from today's cost model, because a prediction keeps the
    #: costs it was made under and re-deriving it under new ones would rewrite history.
    cost_of_acting: float
    #: Exposure on the orders where acting costs more than it saves. Money the business is
    #: choosing to carry, which belongs on the page rather than in the gap between two
    #: numbers.
    absorbed_exposure: float
    priorities: dict[str, int]
    by_shipping_mode: list[Grouped]
    by_region: list[Grouped]

    @property
    def flagged_share(self) -> float:
        return self.flagged / self.scored if self.scored else 0.0

    @property
    def recoverable_share(self) -> float:
        """Recoverable money as a share of exposure.

        The figure that survives more orders being entered. A running total only grows, so
        it cannot be read as "how are we doing" from one week to the next; a share can.
        """
        return self.net_benefit_available / self.value_at_risk if self.value_at_risk else 0.0


def summarise(session: Session) -> Summary:
    """Everything the control tower renders, from the predictions actually stored.

    The aggregate runs over the newest prediction per order rather than over every
    prediction ever made, because re-scoring an order after a retrain would otherwise count
    it twice and weight the busiest orders most heavily.
    """
    newest = _newest_prediction_ids(session)

    orders = session.scalar(select(func.count()).select_from(Order)) or 0
    scored = len(newest)
    if not newest:
        return Summary(
            orders=orders,
            scored=0,
            flagged=0,
            value_at_risk=0.0,
            net_benefit_available=0.0,
            actionable=0,
            cost_of_acting=0.0,
            absorbed_exposure=0.0,
            priorities={},
            by_shipping_mode=[],
            by_region=[],
        )

    flagged = (
        session.scalar(
            select(func.count())
            .select_from(Prediction)
            .where(Prediction.id.in_(newest), Prediction.probability >= Prediction.threshold)
        )
        or 0
    )
    exposure = (
        session.scalar(select(func.sum(Prediction.value_at_risk)).where(Prediction.id.in_(newest)))
        or 0.0
    )
    worth_acting = (
        session.scalar(
            select(func.sum(Prediction.net_benefit)).where(
                Prediction.id.in_(newest), Prediction.net_benefit > 0
            )
        )
        or 0.0
    )

    actionable = (
        session.scalar(
            select(func.count())
            .select_from(Prediction)
            .where(Prediction.id.in_(newest), Prediction.net_benefit > 0)
        )
        or 0
    )
    # `value_at_risk - net_benefit` is the cost of acting plus anything acting is not
    # expected to recover, per row, under whatever cost model that row was scored with.
    # Reading it off the stored figures is what keeps this correct across a cost-model edit.
    spent = (
        session.scalar(
            select(func.sum(Prediction.value_at_risk - Prediction.net_benefit)).where(
                Prediction.id.in_(newest), Prediction.net_benefit > 0
            )
        )
        or 0.0
    )
    absorbed = (
        session.scalar(
            select(func.sum(Prediction.value_at_risk)).where(
                Prediction.id.in_(newest), Prediction.net_benefit <= 0
            )
        )
        or 0.0
    )

    priorities = {
        str(name): int(count)
        for name, count in session.execute(
            select(Prediction.priority, func.count())
            .where(Prediction.id.in_(newest))
            .group_by(Prediction.priority)
        ).all()
    }

    return Summary(
        orders=orders,
        scored=scored,
        flagged=int(flagged),
        value_at_risk=float(exposure),
        net_benefit_available=float(worth_acting),
        actionable=int(actionable),
        cost_of_acting=float(spent),
        absorbed_exposure=float(absorbed),
        priorities=priorities,
        by_shipping_mode=_grouped(session, Order.shipping_mode, newest),
        by_region=_grouped(session, Order.order_region, newest),
    )


def _newest_prediction_ids(session: Session) -> list[int]:
    """The id of the latest prediction for each order, so a re-score does not count twice."""
    return list(
        session.scalars(select(func.max(Prediction.id)).group_by(Prediction.order_id)).all()
    )


def _grouped(
    session: Session, column: InstrumentedAttribute[str], newest: list[int]
) -> list[Grouped]:
    """Mean predicted risk per group, with the group's size, most orders first."""
    rows = session.execute(
        select(column, func.avg(cast(Prediction.probability, Float)), func.count())
        .join(Prediction, Prediction.order_id == Order.id)
        .where(Prediction.id.in_(newest))
        .group_by(column)
        .order_by(func.count().desc())
    ).all()
    return [Grouped(str(label), float(mean), int(count)) for label, mean, count in rows]
