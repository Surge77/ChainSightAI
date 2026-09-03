"""One `render`, so no page can forget who is signed in, or what the money is denominated in.

`base.html` branches on `user` to draw the navigation, and a route that renders a template
without passing it would silently show the signed-out header to a signed-in operator.
Jinja treats an undefined name as falsey rather than raising, so the failure is a page that
looks slightly wrong rather than an error anybody would notice.

Routing every response through one function makes `user` a parameter that cannot be
omitted, which is the cheapest possible fix.

The currency arrives the same way and for the same reason. `money` is put into the context
here, already bound to the currency this application was configured with, so a template
writes `{{ money(x) }}` and cannot render a figure with the wrong symbol or none at all. It
is read off `app.state` rather than held in a module-level Jinja filter, because two
applications with two currencies exist in the test suite and a global would let one of them
answer for the other.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Request, Response
from fastapi.templating import Jinja2Templates

from chainsight.money import DEFAULT_CURRENCY, format_money, symbol_for
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
    currency = currency_for(request)
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context={
            "user": user,
            CSRF_FIELD: token,
            "money": _formatter(currency),
            "currency": currency,
            "currency_symbol": symbol_for(currency),
            **context,
        },
        status_code=status_code,
    )
    set_csrf_cookie(response, token)
    return response


def currency_for(request: Request) -> str:
    """The currency this application was configured with.

    The default covers the one case where there is no application to ask: a template
    rendered outside a configured app, which happens in tests before anything is wired up.
    """
    settings = getattr(request.app.state, "settings", None)
    return getattr(settings, "currency", DEFAULT_CURRENCY)


def _formatter(currency: str) -> Callable[[float], str]:
    """`money(x)` for the templates, with the currency already decided."""

    def money(amount: float) -> str:
        return format_money(amount, currency)

    return money


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
