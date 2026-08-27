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
from chainsight_web.security import COOKIE_NAME, read_session
from chainsight_web.service import ModelService
from chainsight_web.tables import User

#: Where an anonymous visitor is sent when the page they wanted needs a login.
LOGIN_PATH = "/login"


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
    """A logged-in user, or a redirect to the login form."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="this page needs a login",
            headers={"Location": LOGIN_PATH},
        )
    return user


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    """An admin, checked against the database row rather than anything the browser sent.

    A logged-in non-admin gets 403 rather than a redirect. They are not missing a login;
    they are asking for something that is not theirs, and sending them to a login form
    would invite them to try another account.
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this page is for administrators",
        )
    return user
