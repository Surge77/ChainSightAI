"""What an operator can see and do: their own orders, and one more.

Ownership is a `WHERE` clause, never a check after the fetch. `select(Order).where(Order.id
== wanted, Order.user_id == me)` cannot return somebody else's row; `session.get(Order,
wanted)` followed by `if order.user_id != me` can, the first time anybody adds a second
place that fetches an order and forgets the second line. The difference is not stylistic —
one of them is a bug waiting for a careless edit and the other is not.

A missing order and somebody else's order are both 404. Distinguishing them would confirm
that an id exists, which is the whole of what an attacker enumerating ids wants to learn.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from chainsight_web.dependencies import current_user, get_service, get_session, require_user
from chainsight_web.schemas import OrderInput
from chainsight_web.service import ModelService, ServiceError, categories_of, predict_for
from chainsight_web.tables import ORDER_COLUMNS, Order, Prediction, User
from chainsight_web.templating import render

router = APIRouter(tags=["orders"])

#: The categorical fields, as the form names them, in the order the form shows them.
CHOICE_FIELDS: tuple[str, ...] = (
    "shipping_mode",
    "payment_type",
    "market",
    "order_region",
    "order_country",
    "customer_country",
    "customer_state",
    "customer_segment",
    "department_name",
    "category_name",
    "product_name",
)

#: What each field is called on the page. The dataset's own names are not English.
LABELS: dict[str, str] = {
    "shipping_mode": "Shipping mode",
    "payment_type": "Payment type",
    "market": "Market",
    "order_region": "Order region",
    "order_country": "Destination country",
    "customer_country": "Customer country",
    "customer_state": "Customer state",
    "customer_segment": "Customer segment",
    "department_name": "Department",
    "category_name": "Category",
    "product_name": "Product",
}

#: Dropdowns are built from the fitted categories, keyed by the dataset's column names.
_DATASET_NAME = {column: dataset for dataset, column in ORDER_COLUMNS.items()}


@router.get("/")
def home(user: Annotated[User | None, Depends(current_user)]) -> Response:
    if user is not None:
        return RedirectResponse("/orders", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/orders")
def list_orders(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """This operator's orders, ranked by what acting on them is worth."""
    orders = session.scalars(select(Order).where(Order.user_id == user.id)).all()
    latest = {order.id: _latest_prediction(session, order.id) for order in orders}

    rows = sorted(
        ((order, latest[order.id]) for order in orders),
        key=lambda pair: pair[1].net_benefit if pair[1] else float("-inf"),
        reverse=True,
    )
    return render(request, "orders.html", user=user, rows=rows)


@router.get("/orders/new")
def new_order_form(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    service: Annotated[ModelService, Depends(get_service)],
) -> Response:
    try:
        _, artefact = service.live()
    except ServiceError as absent:
        return render(request, "new_order.html", user=user, choices=None, blocked=str(absent))

    fitted = categories_of(artefact)
    choices = {field: fitted[_DATASET_NAME[field]] for field in CHOICE_FIELDS}
    return render(
        request,
        "new_order.html",
        user=user,
        choices=choices,
        labels=LABELS,
        default_ordered_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M"),
    )


@router.post("/orders/new")
def create_order(
    request: Request,
    submitted: Annotated[OrderInput, Form()],
    user: Annotated[User, Depends(require_user)],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[ModelService, Depends(get_service)],
) -> Response:
    order = Order(user_id=user.id, **submitted.model_dump())
    session.add(order)
    session.commit()

    try:
        predict_for(session, service, order)
    except ServiceError as absent:
        # The order is kept. It is a real order that a real operator entered, and throwing
        # it away because the model is unavailable would lose work to an unrelated failure.
        return render(
            request,
            "report.html",
            user=user,
            order=order,
            prediction=None,
            fields=_readable(order),
            error=str(absent),
            status_code=503,
        )

    return RedirectResponse(f"/orders/{order.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/orders/{order_id}")
def order_report(
    request: Request,
    order_id: int,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """One order and what the system said about it. Filtered by owner in the query."""
    order = session.scalars(
        select(Order).where(Order.id == order_id, Order.user_id == user.id)
    ).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such order")

    return render(
        request,
        "report.html",
        user=user,
        order=order,
        prediction=_latest_prediction(session, order.id),
        fields=_readable(order),
    )


def _latest_prediction(session: Session, order_id: int) -> Prediction | None:
    return session.scalars(
        select(Prediction)
        .where(Prediction.order_id == order_id)
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
    ).first()


def _readable(order: Order) -> list[tuple[str, object]]:
    """The order as label-and-value pairs, for the report's table."""
    pairs = [(LABELS[field], getattr(order, field)) for field in CHOICE_FIELDS]
    pairs.append(("Quantity", order.quantity))
    pairs.append(("Product price", f"{order.product_price:.2f}"))
    pairs.append(("Order total", f"{order.order_total:.2f}"))
    pairs.append(("Discount rate", f"{order.discount_rate:.2f}"))
    pairs.append(("Ordered at", order.ordered_at.strftime("%Y-%m-%d %H:%M")))
    return pairs
