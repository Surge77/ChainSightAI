"""Six tables, and one rule about where truth lives.

`model_versions` and `training_runs` look like they duplicate `artifacts/registry.json`, and
they would if the application wrote to both. It does not. The JSON registry is the source of
truth — it is what `chainsight train` writes and what `registry.promote` guards — and this
table is a read model, refreshed from it, so that a prediction can record which model
produced it and the admin pages can join rather than parse a file per request.

`orders` stores the at-order fields as columns rather than as a JSON blob. The blob would be
shorter and would drift: the whole point of `features.ORDER_FIELDS` is that the serving path
supplies exactly the fields training used, and a schema that spells them out is a schema
that fails loudly when that changes. `ORDER_COLUMNS` maps one to the other in one place, and
a test asserts the two sets are equal.

Personal data does not appear here at all. The column contract drops nine columns at ingest
and nothing in this schema puts any of them back — an operator's own email is the only
personal thing stored, and it is the login, not a customer's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chainsight_web.database import Base

#: Dataset column name -> database column name. The serving path rebuilds an order frame
#: from this, so the two can never disagree about which field is which.
ORDER_COLUMNS: dict[str, str] = {
    "Type": "payment_type",
    "Category Name": "category_name",
    "Customer Country": "customer_country",
    "Customer Segment": "customer_segment",
    "Customer State": "customer_state",
    "Department Name": "department_name",
    "Market": "market",
    "Order Country": "order_country",
    "Order Region": "order_region",
    "Product Name": "product_name",
    "Shipping Mode": "shipping_mode",
    "Order Item Discount Rate": "discount_rate",
    "Order Item Quantity": "quantity",
    "Order Item Total": "order_total",
    "Product Price": "product_price",
    "order date (DateOrders)": "ordered_at",
}


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    """An operator or an admin. `is_admin` is read from here and nowhere else.

    Never from a form field, a cookie value, a query parameter or a template variable —
    the session cookie carries an id, and the role is looked up against this column on
    every request that needs it.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    orders: Mapped[list[Order]] = relationship(back_populates="owner")


class Order(Base):
    """One order as an operator entered it: the sixteen fields known before dispatch.

    Nothing post-dispatch is stored, because nothing post-dispatch is knowable at the moment
    this row is written. A `delivered_late` column here would be an invitation to train on
    it, and `docs/leakage.md` is thirty accuracy points of argument against that.
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    payment_type: Mapped[str] = mapped_column(String(32))
    category_name: Mapped[str] = mapped_column(String(64))
    customer_country: Mapped[str] = mapped_column(String(64))
    customer_segment: Mapped[str] = mapped_column(String(32))
    customer_state: Mapped[str] = mapped_column(String(32))
    department_name: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(32))
    order_country: Mapped[str] = mapped_column(String(64))
    order_region: Mapped[str] = mapped_column(String(64))
    product_name: Mapped[str] = mapped_column(String(128))
    shipping_mode: Mapped[str] = mapped_column(String(32))
    discount_rate: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)
    order_total: Mapped[float] = mapped_column(Float)
    product_price: Mapped[float] = mapped_column(Float)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    owner: Mapped[User] = relationship(back_populates="orders")
    predictions: Mapped[list[Prediction]] = relationship(back_populates="order")

    def as_fields(self) -> dict[str, Any]:
        """The order in the dataset's own vocabulary, ready for `features.single_order`."""
        return {dataset: getattr(self, column) for dataset, column in ORDER_COLUMNS.items()}


class Prediction(Base):
    """What the model and the decision engine said about one order, at one moment.

    Every field of `decision.Decision` is stored rather than recomputed on read. The cost
    model is editable by an admin, so recomputing would silently rewrite history: a report
    from last week would show today's costs and claim they were the reason for last week's
    priority.
    """

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    model_version: Mapped[int] = mapped_column(Integer, index=True)
    model_name: Mapped[str] = mapped_column(String(64))

    probability: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    expected_profit: Mapped[float] = mapped_column(Float)
    value_at_risk: Mapped[float] = mapped_column(Float)
    net_benefit: Mapped[float] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(16), index=True)
    recommendation: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    order: Mapped[Order] = relationship(back_populates="predictions")


class ModelVersion(Base):
    """A read model of `artifacts/registry.json`, refreshed from it rather than written to.

    `is_live` is a cached copy of the registry's `current`. The registry stays the authority
    because it is what the promotion guard runs against; a second writable copy of "which
    model is serving" is a disagreement waiting to happen.
    """

    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("version", name="one_row_per_registry_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    artefact: Mapped[str] = mapped_column(String(128))
    model_name: Mapped[str] = mapped_column(String(64))
    trained_at: Mapped[str] = mapped_column(String(32))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    feature_hash: Mapped[str] = mapped_column(String(64))
    scores: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(String(256), default="")
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)


class TrainingRun(Base):
    """One retrain triggered from the admin pages, and what happened to it.

    A refused promotion is recorded with the reason rather than discarded. The guard
    refusing a regression is the interesting event, and a control tower that only logs its
    successes is one that cannot show why the model in production is three weeks old.
    """

    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    triggered_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    model_name: Mapped[str] = mapped_column(String(64))
    rows_trained: Mapped[int] = mapped_column(Integer)
    seconds: Mapped[float] = mapped_column(Float)
    scores: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    registered_version: Mapped[int] = mapped_column(Integer)
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DecisionConfig(Base):
    """The cost model an admin edited, and who edited it.

    These numbers are assumptions with no empirical basis in this dataset, which is the
    whole argument of `docs/decision_engine.md`. Storing them in a table with an author and
    a timestamp keeps that visible: they are somebody's stated business judgement, dated,
    rather than constants that arrived from nowhere.
    """

    __tablename__ = "decision_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intervention: Mapped[float] = mapped_column(Float)
    margin_lost_when_late: Mapped[float] = mapped_column(Float)
    fixed_penalty_when_late: Mapped[float] = mapped_column(Float)
    mean_margin: Mapped[float] = mapped_column(Float)
    typical_order_value: Mapped[float] = mapped_column(Float)
    critical_above: Mapped[float] = mapped_column(Float)
    high_above: Mapped[float] = mapped_column(Float)
    monitor_above: Mapped[float] = mapped_column(Float)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RoleChange(Base):
    """Who granted or revoked the administrator role, to whom, and when.

    The role is the most sensitive thing this application can change about an account, and
    it is now changeable from a browser rather than only from a shell on the server. That
    trade is only acceptable if every change is attributable, so this table is written on
    the same commit as the change itself and is shown on the page that makes them.

    Two foreign keys point at `users` and neither carries a relationship. `actor` and
    `subject` would both need an explicit join condition to disambiguate, and nothing here
    navigates from a user to their role changes -- the page reads this table directly.

    The two email columns duplicate what the join would give, deliberately. An audit row
    has to stay readable after the account it names is gone, and a log that renders as
    `user 7 promoted user 12` once the rows are deleted has recorded nothing worth keeping.
    """

    __tablename__ = "role_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    actor_email: Mapped[str] = mapped_column(String(320))
    subject_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject_email: Mapped[str] = mapped_column(String(320))
    #: True when the role was granted, False when it was taken away.
    granted: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
