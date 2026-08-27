"""One `render`, so no page can forget who is signed in.

`base.html` branches on `user` to draw the navigation, and a route that renders a template
without passing it would silently show the signed-out header to a signed-in operator.
Jinja treats an undefined name as falsey rather than raising, so the failure is a page that
looks slightly wrong rather than an error anybody would notice.

Routing every response through one function makes `user` a parameter that cannot be
omitted, which is the cheapest possible fix.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request, Response
from fastapi.templating import Jinja2Templates

from chainsight_web.tables import User

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render(
    request: Request,
    name: str,
    *,
    user: User | None,
    status_code: int = 200,
    **context: Any,
) -> Response:
    """Render a template with the signed-in user always in scope."""
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={"user": user, **context},
        status_code=status_code,
    )
