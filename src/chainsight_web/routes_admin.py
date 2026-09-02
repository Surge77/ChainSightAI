"""The control tower: what the system has said, what is serving, and what it costs to act.

Three things here are worth naming before the code.

**Retraining reads a file on the server, never the database.** `settings.dataset` is the
training set, and nothing an operator types into the order form reaches it. `SECURITY.md`
lists "an operator poisoning the retraining set through the UI" among the things this
project does not defend against; in this design there is no path for it, and that is a
property of where the training data comes from rather than a check somewhere.

**Promotion goes through `registry.promote`.** The compare-then-promote guard is one
implementation, in one place, and this route calls it. A second copy of "is the new model
better" living in a request handler is a second copy that will disagree.

**Every handler here is `def`, not `async def`.** A retrain is minutes of CPU-bound
scikit-learn, and inside an `async` handler that would block the event loop and stall every
other request in the process. FastAPI runs a synchronous handler in a threadpool, which is
exactly what this work wants.
"""

from __future__ import annotations

import time
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from chainsight import decision, models, persistence, registry, training
from chainsight_web.analytics import NOISY_BELOW, summarise
from chainsight_web.config import Settings
from chainsight_web.dependencies import get_service, get_session, get_settings, require_admin
from chainsight_web.schemas import CostInput, Promotion, RetrainInput
from chainsight_web.service import ModelService, costs_in, sync_versions
from chainsight_web.tables import DecisionConfig, ModelVersion, TrainingRun, User
from chainsight_web.templating import render

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("")
def dashboard(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[ModelService, Depends(get_service)],
) -> Response:
    live = service.known.current()
    return render(
        request,
        "admin_dashboard.html",
        user=admin,
        summary=summarise(session),
        live=live,
        noisy_below=NOISY_BELOW,
    )


@router.get("/models")
def model_registry(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[ModelService, Depends(get_service)],
    notice: str | None = None,
    error: str | None = None,
) -> Response:
    """The registry, refreshed from its JSON before it is shown.

    Refreshing on read rather than on a schedule means a model promoted from a terminal is
    visible here on the next page load, with no background job to be wrong about.
    """
    sync_versions(session, service.known)
    return render(
        request,
        "admin_models.html",
        user=admin,
        versions=session.scalars(select(ModelVersion).order_by(ModelVersion.version.desc())).all(),
        runs=session.scalars(
            select(TrainingRun).order_by(TrainingRun.created_at.desc()).limit(10)
        ).all(),
        candidates=models.names(),
        default_model=training.PRODUCTION_MODEL,
        metric=registry.DEFAULT_METRIC,
        notice=notice,
        error=error,
    )


@router.post("/models/promote")
def promote(
    promotion: Annotated[Promotion, Form()],
    admin: Annotated[User, Depends(require_admin)],
    service: Annotated[ModelService, Depends(get_service)],
) -> Response:
    try:
        entry = service.known.promote(promotion.version, force=promotion.force)
    except registry.RegistryError as refusal:
        return _back_to_models(error=str(refusal))

    service.forget()
    return _back_to_models(
        notice=f"Version {entry.version} ({entry.model_name}) is now scoring your orders."
    )


@router.post("/models/retrain")
def retrain(
    submitted: Annotated[RetrainInput, Form()],
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[ModelService, Depends(get_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Fit a fresh model on the server's dataset, register it, and offer it to the guard."""
    if not settings.dataset.is_file():
        return _back_to_models(
            error=(
                f"There is no dataset to train on: {settings.dataset} is not on this "
                "machine. Fetch it onto the server first."
            )
        )

    try:
        candidate = models.by_name(submitted.model_name)
    except KeyError as unknown:
        return _back_to_models(error=str(unknown))

    started = time.perf_counter()
    run = training.train(settings.dataset, model_name=candidate.name, costs=costs_in(session))
    elapsed = time.perf_counter() - started

    name = training.artefact_name(run)
    persistence.save(run.artefact, name, directory=settings.artefacts)
    entry = service.known.register(run.manifest, name, note=submitted.note)

    promoted, outcome = _try_promotion(service, entry.version, wanted=submitted.promote)
    session.add(
        TrainingRun(
            triggered_by=admin.id,
            model_name=run.manifest.model_name,
            rows_trained=run.rows_trained,
            seconds=elapsed,
            scores=dict(run.scores),
            registered_version=entry.version,
            promoted=promoted,
            outcome=outcome,
        )
    )
    session.commit()

    return _back_to_models(notice=outcome) if promoted else _back_to_models(error=outcome)


def _try_promotion(service: ModelService, version: int, *, wanted: bool) -> tuple[bool, str]:
    """Ask the guard, and report what it said either way.

    A refusal is recorded rather than discarded. The guard turning down a retrain is the
    interesting event: it is why the model in production is three weeks old, and a control
    tower that logs only its successes cannot answer that question.
    """
    if not wanted:
        return False, (
            f"Version {version} was trained and saved. It is not scoring anything yet — "
            "use it from the table above when you are ready."
        )

    try:
        service.known.promote(version)
    except registry.RegistryError as refusal:
        return False, (f"Version {version} was trained and saved, but not switched on: {refusal}")

    service.forget()
    return True, f"Version {version} was trained and is now scoring your orders."


@router.get("/costs")
def cost_form(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    return render(
        request,
        "admin_costs.html",
        user=admin,
        costs=costs_in(session),
        defaults=decision.CostModel(),
    )


@router.post("/costs")
def update_costs(
    request: Request,
    submitted: Annotated[CostInput, Form()],
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Store a new cost model. Past predictions keep the numbers they were made under."""
    session.add(DecisionConfig(**submitted.model_dump(), updated_by=admin.id))
    session.commit()

    return render(
        request,
        "admin_costs.html",
        user=admin,
        costs=costs_in(session),
        defaults=decision.CostModel(),
        notice=(
            "Saved. Orders scored from now on use these numbers. Reports already produced "
            "keep the ones they were made with, so a report always says what the system "
            "actually said at the time."
        ),
    )


def _back_to_models(*, notice: str | None = None, error: str | None = None) -> Response:
    """Redirect after a post, so a refresh does not retrain or re-promote.

    The message travels in the query string and is encoded on the way out and escaped by
    Jinja on the way back in. A sentence built from an exception can contain anything, and
    a path or a filename with an `&` in it should not be able to invent a second parameter.
    """
    carried = {"notice": notice} if notice else {"error": error} if error else {}
    query = f"?{urlencode(carried)}" if carried else ""
    return RedirectResponse(f"/admin/models{query}", status_code=status.HTTP_303_SEE_OTHER)
