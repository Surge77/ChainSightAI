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

from chainsight_web.security import CSRF_COOKIE, CSRF_FIELD, new_csrf_token
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
    """Render a template with the signed-in user and a CSRF token always in scope.

    The token is minted here, for the same reason `user` is passed here: this is the one
    function every page goes through, so it is the one place that cannot be forgotten. A
    visitor arriving without a token gets one issued on this response, and the identical
    value goes into the context for the forms to carry back.

    Reusing the token already in the request rather than minting one per render matters. A
    page can be open in two tabs, and a fresh token per render would invalidate whichever
    form the person did not submit last.
    """
    token = request.cookies.get(CSRF_COOKIE) or new_csrf_token()
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context={"user": user, CSRF_FIELD: token, **context},
        status_code=status_code,
    )
    set_csrf_cookie(response, token)
    return response


def set_csrf_cookie(response: Response, token: str) -> None:
    """Attach the CSRF cookie. `HttpOnly`, because nothing here reads it from a script.

    The form carries the token because the server rendered it into the HTML, not because
    JavaScript fetched it out of the cookie — so the cookie can stay unreadable to scripts,
    and an XSS that would otherwise hand an attacker a matching pair does not.
    """
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=True,
        samesite="lax",
    )
