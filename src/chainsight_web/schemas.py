"""Everything arriving from a browser stops here first.

The WebView is untrusted, the form is untrusted, and a route that reads
`form["order_total"]` and multiplies it by a probability is a route that will one day
multiply a probability by `"; DROP TABLE"`. So every posted body is a Pydantic model, and
the route receives a validated object or FastAPI has already returned a 422.

The bounds are not decorative. `quantity` is at least one because an order of zero items is
not an order; `discount_rate` is a share and belongs in [0, 1]; `order_total` may be zero
because fully discounted orders exist in this table, but may not be negative because
`decision.decide` refuses a negative total and a 500 is a worse answer than a field error.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from chainsight_web.security import MIN_PASSWORD_LENGTH

#: Long enough for the longest product name in the catalogue, short enough that a megabyte
#: of text in a form field is rejected at the boundary rather than stored.
MAX_TEXT = 128


class Credentials(BaseModel):
    """A login. Deliberately says nothing about why it failed."""

    email: str = Field(max_length=320)
    password: str = Field(max_length=72)


class Registration(BaseModel):
    """A new operator account. The role is not here, and cannot be.

    `is_admin` is absent from this model on purpose. A registration form that carried the
    role would let anybody who can post a form make themselves an admin, and no amount of
    checking the value afterwards fixes a field that should never have been accepted.
    """

    email: str = Field(max_length=320)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=72)

    @field_validator("email")
    @classmethod
    def looks_like_an_address(cls, value: str) -> str:
        """A shape check, not RFC 5322.

        Full email validation needs a dependency, and this application never sends mail —
        the address is a login. Rejecting something with no `@` catches the typo; claiming
        to validate more than that would be claiming more than is checked.
        """
        local, _, domain = value.partition("@")
        if not local or "." not in domain:
            raise ValueError("that does not look like an email address")
        return value.lower()


class OrderInput(BaseModel):
    """The sixteen fields known when an order is placed, and nothing that is not.

    A field for the delivery outcome would be the leak the whole project is about, so the
    shape of this model is the argument in `docs/leakage.md` expressed as a schema.
    """

    payment_type: str = Field(max_length=32)
    category_name: str = Field(max_length=MAX_TEXT)
    customer_country: str = Field(max_length=64)
    customer_segment: str = Field(max_length=32)
    customer_state: str = Field(max_length=32)
    department_name: str = Field(max_length=64)
    market: str = Field(max_length=32)
    order_country: str = Field(max_length=64)
    order_region: str = Field(max_length=64)
    product_name: str = Field(max_length=MAX_TEXT)
    shipping_mode: str = Field(max_length=32)
    discount_rate: float = Field(ge=0.0, le=1.0)
    quantity: int = Field(ge=1, le=1000)
    order_total: float = Field(ge=0.0)
    product_price: float = Field(ge=0.0)
    ordered_at: datetime


class CostInput(BaseModel):
    """An admin's edit to the cost model.

    The bands are checked here as well as in `decision.CostModel.__post_init__`, and that
    duplication is deliberate: the dataclass raising is a 500, and an admin who typed a
    high band above a critical one deserves a field error saying so.
    """

    intervention: float = Field(gt=0.0)
    margin_lost_when_late: float = Field(ge=0.0, le=1.0)
    fixed_penalty_when_late: float = Field(ge=0.0)
    mean_margin: float = Field(ge=0.0, le=1.0)
    typical_order_value: float = Field(gt=0.0)
    critical_above: float
    high_above: float
    monitor_above: float

    @field_validator("monitor_above")
    @classmethod
    def bands_descend(cls, value: float, info: ValidationInfo) -> float:
        """Otherwise a band is unreachable and orders silently skip a priority."""
        critical = info.data.get("critical_above")
        high = info.data.get("high_above")
        if critical is None or high is None:
            return value
        if not critical > high > value:
            raise ValueError("the priority bands must descend: critical > high > monitor")
        return value


class Promotion(BaseModel):
    """Which registered version an admin wants serving, and whether they mean it."""

    version: int = Field(ge=1)
    force: bool = False


class RoleAssignment(BaseModel):
    """One administrator changing another account's role.

    `make_admin` is an explicit boolean carried by a hidden field rather than a checkbox.
    An unchecked checkbox is simply absent from the submission, so the form would say
    nothing and the route would have to read that silence as "revoke" -- which is a lot of
    consequence to hang on a field that is not there.
    """

    user_id: int = Field(ge=1)
    make_admin: bool


class RetrainInput(BaseModel):
    """A retrain request. `promote` asks for it; the guard decides whether it happens."""

    model_name: str = Field(max_length=64)
    note: str = Field(default="", max_length=256)
    promote: bool = False
