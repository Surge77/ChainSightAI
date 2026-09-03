"""Registering, signing in, and signing out.

One rule shapes every response here: a failed login says the same thing whichever half was
wrong. "No such account" and "wrong password" are two different sentences, and the
difference between them is a way to find out which addresses have accounts.

The account created by registration is always an operator. There is no field for the role,
no first-user-becomes-admin shortcut, and no branch that could grant one — an admin is made
by `python -m chainsight_web init` or by an existing admin, both of which happen server-side
with no browser involved.

Every route below is a POST a stranger can reach, so each one spends from a budget held
against the address it came from. `throttle.py` argues the design; the part that matters
here is that the refusal says the same thing to everybody and names no account, exactly as
`REJECTED` does, and that a wrong password at the administrator's door spends from the same
budget as a wrong password at the operator's.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from chainsight_web import throttle
from chainsight_web.config import Settings
from chainsight_web.dependencies import current_user, get_session, get_settings
from chainsight_web.schemas import Credentials, Registration
from chainsight_web.security import (
    COOKIE_NAME,
    CSRF_COOKIE,
    MIN_PASSWORD_LENGTH,
    hash_password,
    new_csrf_token,
    sign_session,
    verify_password,
)
from chainsight_web.tables import User
from chainsight_web.templating import render, set_csrf_cookie

router = APIRouter(tags=["auth"])

#: The same sentence for an unknown address and a wrong password, on purpose.
REJECTED = "That email and password do not match an account."

#: Where a successful sign-in lands.
AFTER_LOGIN = "/orders"

#: Where a successful administrator sign-in lands.
AFTER_ADMIN_LOGIN = "/admin"


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
    client = throttle.client_address(request)
    remaining = throttle.retry_after(session, throttle.SIGN_IN, client)
    if remaining is not None:
        return render(
            request,
            "login.html",
            user=None,
            error=throttle.wait_message(remaining),
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    account = _authenticate(session, credentials)
    if account is None:
        throttle.record(session, throttle.SIGN_IN, client)
        return render(request, "login.html", user=None, error=REJECTED, status_code=400)

    return _signed_in(account, settings)


@router.get("/admin/login")
def admin_login_form(
    request: Request, user: Annotated[User | None, Depends(current_user)]
) -> Response:
    """The administrator's door. A separate page, not a separate mechanism.

    An operator who is already signed in is sent to their own pages rather than shown this
    form: they are not missing a login, and offering them one here would invite them to go
    looking for a second account.
    """
    if user is not None:
        return RedirectResponse(
            AFTER_ADMIN_LOGIN if user.is_admin else AFTER_LOGIN,
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return render(request, "admin_login.html", user=None)


@router.post("/admin/login")
def admin_sign_in(
    request: Request,
    credentials: Annotated[Credentials, Form()],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Authenticate, then check the role that is already on the account.

    Two properties matter more than the convenience of a separate page, and both are tested.

    **This form cannot grant the role.** It reads `is_admin` from the row, exactly as
    `require_admin` does on every request. Signing in here makes nobody an administrator.

    **It says the same thing to a non-administrator as to a wrong password.** Otherwise the
    page becomes an oracle: post a valid operator's credentials, read a different message,
    and you have learned that the account exists and is not an administrator — and, by
    elimination, which accounts are. No cookie is set on that path either, so a refused
    operator leaves with exactly what they arrived with.
    """
    client = throttle.client_address(request)
    remaining = throttle.retry_after(session, throttle.SIGN_IN, client)
    if remaining is not None:
        return render(
            request,
            "admin_login.html",
            user=None,
            error=throttle.wait_message(remaining),
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    account = _authenticate(session, credentials)
    if account is None or not account.is_admin:
        # A valid operator refused here spends an attempt too. Otherwise the one credential
        # this page is guaranteed to reject would be the one that buys unlimited guesses.
        throttle.record(session, throttle.SIGN_IN, client)
        return render(request, "admin_login.html", user=None, error=REJECTED, status_code=400)

    return _signed_in(account, settings, landing=AFTER_ADMIN_LOGIN)


def _authenticate(session: Session, credentials: Credentials) -> User | None:
    """The account these credentials open, or `None`. Says nothing about which half failed.

    `verify_password` is called against a dummy hash when the account is absent, so that a
    missing account and a wrong password take about the same time. Timing is the other way
    the two cases leak apart.
    """
    account = session.scalars(
        select(User).where(User.email == credentials.email.strip().lower())
    ).first()

    stored = account.password_hash if account else _DUMMY_HASH
    matched = verify_password(credentials.password, stored)
    return account if account is not None and matched else None


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
    client = throttle.client_address(request)
    remaining = throttle.retry_after(session, throttle.REGISTRATION, client)
    if remaining is not None:
        return render(
            request,
            "register.html",
            user=None,
            min_password_length=MIN_PASSWORD_LENGTH,
            error=throttle.wait_message(remaining),
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # Spent whatever happens next, unlike the sign-in budget. The abuse this budget exists
    # for is a table filled with accounts, so a *successful* registration is the thing worth
    # counting; and posting repeatedly at addresses that turn out to be taken is how you
    # find out which addresses are taken, so that path counts too.
    throttle.record(session, throttle.REGISTRATION, client)

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
    response.delete_cookie(CSRF_COOKIE)
    return response


def _signed_in(account: User, settings: Settings, *, landing: str = AFTER_LOGIN) -> Response:
    """Set the signed cookie and send the browser on.

    `httponly` because no script here needs to read it and a script that can read it is a
    script that can exfiltrate it. `samesite=lax` so a form posted from another origin
    cannot ride along on this session. `secure` is deliberately off: this application binds
    to localhost over plain HTTP, and a cookie marked secure would simply never be sent.
    """
    response = RedirectResponse(landing, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        COOKIE_NAME,
        sign_session(account.id, secret=settings.session_secret),
        max_age=settings.session_seconds,
        httponly=True,
        samesite="lax",
    )
    # A new session gets a new CSRF token. Carrying the old one across a login would let a
    # token an attacker had already fixed in the browser keep working against the account
    # that has just signed in, which is the CSRF half of session fixation.
    set_csrf_cookie(response, new_csrf_token())
    return response


#: A real bcrypt hash of a value nobody can log in with, used to keep the timing of a
#: missing account close to the timing of a wrong password.
_DUMMY_HASH = hash_password("this is not a password anybody has")
