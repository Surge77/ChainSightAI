"""Who is asking, what they may see, and where the database session comes from.

The role check is the load-bearing part. `require_admin` reads `is_admin` from the user row
it just fetched by id — not from the cookie, not from a form field, not from a template
variable, and not from anything the browser could have set. The cookie's signature proves
only that the id in it is the one this server issued; it proves nothing about what that user
is allowed to do now, and a role cached in a cookie is a role that survives being revoked.

An anonymous request to a page that needs a login is a redirect rather than a 401. This is a
server-rendered application: a browser that follows a 401 shows a blank page, and a browser
that follows a 303 shows the login form.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from chainsight_web.config import Settings
from chainsight_web.database import session_scope
from chainsight_web.security import COOKIE_NAME, CSRF_COOKIE, CSRF_FIELD, csrf_matches, read_session
from chainsight_web.service import ModelService
from chainsight_web.tables import User

#: Where an anonymous visitor is sent when the page they wanted needs a login.
LOGIN_PATH = "/login"

#: And where they are sent when the page they wanted needs an administrator.
ADMIN_LOGIN_PATH = "/admin/login"

#: Where somebody holding a temporary password is held until they replace it.
CHANGE_PASSWORD_PATH = "/password"

#: Methods that change nothing, and therefore need no CSRF token.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_service(request: Request) -> ModelService:
    service: ModelService = request.app.state.service
    return service


def get_session(request: Request) -> Iterator[Session]:
    yield from session_scope(request.app.state.sessions)


def current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User | None:
    """The signed-in user, or `None`. Never raises, so pages can render either way."""
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie is None:
        return None

    user_id = read_session(cookie, secret=settings.session_secret, max_age=settings.session_seconds)
    if user_id is None:
        return None

    # A `get` by primary key, so a deleted account stops working the moment it is deleted
    # rather than when its cookie happens to expire.
    return session.get(User, user_id)


def require_user(user: Annotated[User | None, Depends(current_user)]) -> User:
    """A logged-in user who has replaced any temporary password, or a redirect."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="this page needs a login",
            headers={"Location": LOGIN_PATH},
        )
    _held_until_password_changed(user)
    return user


def _held_until_password_changed(user: User) -> None:
    """Send somebody still holding an administrator-set password to replace it.

    This is what makes an administrator-created account acceptable at all. Without it the
    password an administrator typed keeps working for the life of the account, the
    administrator knows it, and every action by that account is deniable — "that could have
    been the admin". The temporary password opens exactly one door, and that door is this
    one.
    """
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="this account still has the password it was given",
            headers={"Location": CHANGE_PASSWORD_PATH},
        )


def require_admin(user: Annotated[User | None, Depends(current_user)]) -> User:
    """An admin, checked against the database row rather than anything the browser sent.

    The two failure cases are deliberately different, because they are different situations.

    An anonymous visitor is sent to the administrator sign-in form rather than the operator
    one — they are simply not signed in, and the door they wanted is the admin door.

    A signed-in non-admin gets 403, not a redirect. They are not missing a login; they are
    asking for something that is not theirs, and sending them to a login form would invite
    them to go looking for a second account.
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="this page needs an administrator login",
            headers={"Location": ADMIN_LOGIN_PATH},
        )
    _held_until_password_changed(user)
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this page is for administrators",
        )
    return user


async def verify_csrf(request: Request) -> None:
    """Refuse any state-changing request that does not carry a matching CSRF token.

    This is registered once, on the application, rather than listed on each route that
    needs it. A per-route dependency is a thing somebody has to remember when they add the
    next form, and the failure mode of forgetting is silent: the route works perfectly and
    is simply unprotected. Registered globally it fails closed — a new POST without a token
    is refused until its form is fixed, which is a loud, immediate, harmless failure.

    The scheme is double-submit. A random token lives in its own cookie, the same value is
    rendered into every form, and the two have to match. The cookie is `HttpOnly`, so a
    script cannot read it; `SameSite=Lax` already stops a cross-site form post carrying it;
    and an attacker who can do neither cannot produce a pair that matches.

    Reading the form here is safe alongside a route that also declares one. Starlette caches
    the parsed body on the request, and FastAPI hands dependencies and the endpoint the same
    request object, so the body is parsed once and shared.
    """
    if request.method in SAFE_METHODS:
        return

    submitted = (await request.form()).get(CSRF_FIELD)
    expected = request.cookies.get(CSRF_COOKIE)
    if not csrf_matches(submitted if isinstance(submitted, str) else None, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "That form was missing its security token, or the token did not match. "
                "Reload the page and try again."
            ),
        )
