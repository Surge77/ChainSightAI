"""Assemble the application. One factory, so a test gets a real app rather than a mock.

Everything the routes need lives on `app.state` and is read through the dependencies in
`dependencies.py`. That indirection buys one thing worth having: a test can build an app on
a temporary database, with a temporary artefacts directory, without patching a module-level
global that another test is also using.

There is no CORS middleware, deliberately. The UI is server-rendered from this origin, so
there is no cross-origin case to permit, and a permissive CORS policy added "just in case"
is a policy nobody has thought about.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from chainsight_web import routes_accounts, routes_admin, routes_auth, routes_orders
from chainsight_web.config import Settings
from chainsight_web.database import build_engine, build_sessions, create_tables
from chainsight_web.dependencies import verify_csrf
from chainsight_web.service import ModelService
from chainsight_web.templating import STATIC_DIR, render

TITLE = "ChainSight"

DESCRIPTION = (
    "Pre-dispatch late-delivery risk and order margin on a leakage-audited feature set, "
    "behind a cost-sensitive decision engine."
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application against these settings, creating any missing tables."""
    settings = settings or Settings.from_env()

    # `verify_csrf` is registered on the application rather than on each route that needs
    # it, so a form added later is protected without anybody remembering to protect it.
    app = FastAPI(title=TITLE, description=DESCRIPTION, dependencies=[Depends(verify_csrf)])
    engine = build_engine(settings.database_url)
    create_tables(engine)

    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = build_sessions(engine)
    app.state.service = ModelService(artefacts=settings.artefacts)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(routes_auth.router)
    app.include_router(routes_orders.router)
    app.include_router(routes_admin.router)
    app.include_router(routes_accounts.router)
    app.include_router(routes_accounts.passwords)
    app.add_exception_handler(StarletteHTTPException, _html_errors)
    return app


async def _html_errors(request: Request, exc: Exception) -> Response:
    """Render an error as a page, unless it is a redirect wearing an exception's clothes.

    `require_user` raises a 303 so that an anonymous visitor is sent to the login form, and
    a redirect rendered as an error page would show "303" to somebody who simply needs to
    sign in. Everything else becomes a readable page rather than FastAPI's JSON, because a
    browser showing `{"detail": "no such order"}` is a browser showing a bug.
    """
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - handler is registered
        raise exc  # for StarletteHTTPException only, so this is unreachable in practice
    if "Location" in (exc.headers or {}):
        return await http_exception_handler(request, exc)

    return render(
        request,
        "error.html",
        user=None,
        status=exc.status_code,
        detail=str(exc.detail),
        status_code=exc.status_code,
    )
