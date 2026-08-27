"""Accounts, and the one thing an administrator can change about somebody else.

`ADR 0009` says the administrator role is never self-granted, and that is still true here.
What it never said — and what the CLI-only version quietly implied — is that the role could
not be granted at all without a shell on the server. That is not a security property. It is
a bottleneck, and the thing people do when a bottleneck stands between them and a colleague
who needs access is share the admin password, which destroys attribution completely.

So an administrator can grant and revoke the role from this page. What they still cannot do:

**Choose somebody's password.** An administrator can create an account, because waiting for
a colleague to register themselves before you can give them access is the same bottleneck in
a smaller form. What they cannot do is pick the password: it is generated, shown once, and
`must_change_password` makes it good for exactly one login. Until the owner replaces it the
account reaches nothing but `/password`. That is what keeps an administrator-set password
from being a password the administrator knows for the life of the account.

**Remove the last administrator.** Refused, whoever asks. The failure mode is an application
with no way back in short of the command line, and it is reachable by one careless click on
your own row.

**Do it unattributably.** Every change writes a `RoleChange` row in the same commit, and the
page shows them underneath. An audit nobody can read is a log, not an audit.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chainsight_web.dependencies import current_user, get_session, require_admin
from chainsight_web.schemas import NewAccount, NewPassword, RoleAssignment
from chainsight_web.security import MIN_PASSWORD_LENGTH, hash_password, temporary_password
from chainsight_web.tables import Order, RoleChange, User
from chainsight_web.templating import render

router = APIRouter(prefix="/admin", tags=["accounts"])

#: How many recent role changes the page shows. Enough to see what just happened; the table
#: keeps everything.
RECENT_CHANGES = 10


@router.get("/users")
def list_users(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    notice: str | None = None,
    error: str | None = None,
) -> Response:
    """Every account, its role, and how much it has done."""
    return _page(request, admin, session, notice=notice, error=error)


def _page(
    request: Request,
    admin: User,
    session: Session,
    *,
    notice: str | None = None,
    error: str | None = None,
    issued: str | None = None,
    issued_to: str | None = None,
) -> Response:
    """Render the accounts page. Shared, so a form error shows the page rather than a stub."""
    orders = {
        owner: int(count)
        for owner, count in session.execute(
            select(Order.user_id, func.count()).group_by(Order.user_id)
        ).all()
    }
    accounts = list(session.scalars(select(User).order_by(User.id)))

    return render(
        request,
        "admin_users.html",
        user=admin,
        accounts=[(account, orders.get(account.id, 0)) for account in accounts],
        administrators=sum(1 for account in accounts if account.is_admin),
        changes=list(
            session.scalars(select(RoleChange).order_by(RoleChange.id.desc()).limit(RECENT_CHANGES))
        ),
        notice=notice,
        error=error,
        issued=issued,
        issued_to=issued_to,
    )


@router.post("/users/role")
def set_role(
    assignment: Annotated[RoleAssignment, Form()],
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Grant or revoke the administrator role on an account that already exists."""
    subject = session.get(User, assignment.user_id)
    if subject is None:
        return _back(error=f"there is no account {assignment.user_id}")

    if subject.is_admin == assignment.make_admin:
        role = "an administrator" if subject.is_admin else "an operator"
        return _back(notice=f"{subject.email} is already {role}; nothing changed")

    if not assignment.make_admin and _would_strand(session):
        return _back(
            error=(
                f"{subject.email} is the only administrator. Removing the role would leave "
                "nobody able to grant it back, so it has to be given to somebody else first."
            )
        )

    subject.is_admin = assignment.make_admin
    session.add(
        RoleChange(
            actor_id=admin.id,
            actor_email=admin.email,
            subject_id=subject.id,
            subject_email=subject.email,
            granted=assignment.make_admin,
        )
    )
    session.commit()

    verb = "is now an administrator" if assignment.make_admin else "is now an operator"
    return _back(notice=f"{subject.email} {verb}")


@router.post("/users/new")
def create_account(
    request: Request,
    submitted: Annotated[NewAccount, Form()],
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Create an operator account with a generated one-use password.

    This renders rather than redirecting, which breaks the post-redirect-get pattern used
    everywhere else in this application, and does so on purpose: the temporary password has
    to be shown exactly once and a redirect would have to carry it in the query string,
    where it would land in browser history and any log that records a URL.
    """
    taken = session.scalars(select(User).where(User.email == submitted.email)).first()
    if taken is not None:
        return _page(request, admin, session, error=f"{submitted.email} already has an account")

    password = temporary_password()
    session.add(
        User(
            email=submitted.email,
            password_hash=hash_password(password),
            is_admin=False,
            must_change_password=True,
        )
    )
    session.commit()

    return _page(
        request,
        admin,
        session,
        notice=f"{submitted.email} can sign in once with this password, then must replace it",
        issued=password,
        issued_to=submitted.email,
    )


def _would_strand(session: Session) -> bool:
    """Whether revoking this account's role would leave the application with no way in.

    Counted rather than assumed. An administrator demoting themselves is perfectly
    reasonable when somebody else holds the role, and refusing it outright would be a rule
    about who is asking rather than about what the change does.
    """
    administrators = session.scalar(select(func.count()).select_from(User).where(User.is_admin))
    return (administrators or 0) <= 1


def _back(*, notice: str | None = None, error: str | None = None) -> Response:
    """Redirect after a post, so a refresh does not repeat a role change."""
    carried = {"notice": notice} if notice else {"error": error} if error else {}
    query = f"?{urlencode(carried)}" if carried else ""
    return RedirectResponse(f"/admin/users{query}", status_code=status.HTTP_303_SEE_OTHER)


#: The change-password page is not under `/admin`: the people who need it are operators
#: holding a password an administrator set, and they can reach nothing else until they use it.
passwords = APIRouter(tags=["accounts"])


@passwords.get("/password")
def change_password_form(
    request: Request, user: Annotated[User | None, Depends(current_user)]
) -> Response:
    """Shown to anybody signed in. Only compulsory for a temporary password."""
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return render(
        request,
        "change_password.html",
        user=user,
        forced=user.must_change_password,
        min_password_length=MIN_PASSWORD_LENGTH,
    )


@passwords.post("/password")
def change_password(
    request: Request,
    submitted: Annotated[NewPassword, Form()],
    user: Annotated[User | None, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Replace the password and clear the flag that was holding this account here.

    `current_user` rather than `require_user`, because `require_user` redirects an account
    with a temporary password to this very page — depending on it here would be a loop.
    """
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    account = session.get(User, user.id)
    if account is None:  # pragma: no cover - the session cookie was just resolved to a row
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    account.password_hash = hash_password(submitted.password)
    account.must_change_password = False
    session.commit()

    return RedirectResponse("/orders", status_code=status.HTTP_303_SEE_OTHER)
