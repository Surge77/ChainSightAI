"""Registering, signing in, and signing out.

One rule shapes every response here: a failed login says the same thing whichever half was
wrong. "No such account" and "wrong password" are two different sentences, and the
difference between them is a way to find out which addresses have accounts.

The account created by registration is always an operator. There is no field for the role,
no first-user-becomes-admin shortcut, and no branch that could grant one — an admin is made
by `python -m chainsight_web init` or by an existing admin, both of which happen server-side
with no browser involved.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from chainsight_web.config import Settings
from chainsight_web.dependencies import current_user, get_session, get_settings
from chainsight_web.schemas import Credentials, Registration
from chainsight_web.security import (
    COOKIE_NAME,
    MIN_PASSWORD_LENGTH,
    hash_password,
    sign_session,
    verify_password,
)
from chainsight_web.tables import User
from chainsight_web.templating import render

router = APIRouter(tags=["auth"])

#: The same sentence for an unknown address and a wrong password, on purpose.
REJECTED = "That email and password do not match an account."

#: Where a successful sign-in lands.
AFTER_LOGIN = "/orders"


@router.get("/login")
def login_form(request: Request, user: Annotated[User | None, Depends(current_user)]) -> Response:
    if user is not None:
        return RedirectResponse(AFTER_LOGIN, status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "login.html", user=None)


@router.post("/login")
def sign_in(
    request: Request,
    credentials: Annotated[Credentials, Form()],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    account = session.scalars(
        select(User).where(User.email == credentials.email.strip().lower())
    ).first()

    # `verify_password` is still called against a dummy hash when the account is absent, so
    # that a missing account and a wrong password take about the same time. Timing is the
    # other way the two cases leak apart.
    stored = account.password_hash if account else _DUMMY_HASH
    matched = verify_password(credentials.password, stored)
    if account is None or not matched:
        return render(request, "login.html", user=None, error=REJECTED, status_code=400)

    return _signed_in(account, settings)


@router.get("/register")
def register_form(
    request: Request, user: Annotated[User | None, Depends(current_user)]
) -> Response:
    if user is not None:
        return RedirectResponse(AFTER_LOGIN, status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "register.html", user=None, min_password_length=MIN_PASSWORD_LENGTH)


@router.post("/register")
def register(
    request: Request,
    registration: Annotated[Registration, Form()],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    taken = session.scalars(select(User).where(User.email == registration.email)).first()
    if taken is not None:
        return render(
            request,
            "register.html",
            user=None,
            min_password_length=MIN_PASSWORD_LENGTH,
            error="That email already has an account.",
            status_code=400,
        )

    account = User(
        email=registration.email,
        password_hash=hash_password(registration.password),
        is_admin=False,
    )
    session.add(account)
    session.commit()
    return _signed_in(account, settings)


@router.post("/logout")
def sign_out() -> Response:
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME)
    return response


def _signed_in(account: User, settings: Settings) -> Response:
    """Set the signed cookie and send the browser on.

    `httponly` because no script here needs to read it and a script that can read it is a
    script that can exfiltrate it. `samesite=lax` so a form posted from another origin
    cannot ride along on this session. `secure` is deliberately off: this application binds
    to localhost over plain HTTP, and a cookie marked secure would simply never be sent.
    """
    response = RedirectResponse(AFTER_LOGIN, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        COOKIE_NAME,
        sign_session(account.id, secret=settings.session_secret),
        max_age=settings.session_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


#: A real bcrypt hash of a value nobody can log in with, used to keep the timing of a
#: missing account close to the timing of a wrong password.
_DUMMY_HASH = hash_password("this is not a password anybody has")
