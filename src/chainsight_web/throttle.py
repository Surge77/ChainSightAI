"""A budget of unauthenticated attempts per source address, and what it deliberately is not.

`SECURITY.md` listed this under "what is not defended against": *nothing counts failed
attempts or delays a repeat, so an attacker with a candidate list is limited only by
bcrypt's own cost*. This module counts them.

**It counts per source address, not per account.** Locking an account after N wrong
passwords is the more familiar design and it hands anybody on the internet a way to lock
anybody else out by typing rubbish at their address — a denial of service introduced to fix
a brute force. Counting per address is also strictly stronger against the attacker actually
named above: one source trying many passwords at one account and one source trying one
password at many accounts land in the same bucket, because the bucket is the source.

**What that leaves open, stated rather than discovered.** An attacker distributing the same
candidate list across many source addresses is not slowed down by this at all. Closing that
needs per-account counting and therefore needs an answer to the lockout-as-denial-of-service
problem above; neither is here. `SECURITY.md` says so in the same words.

**The window slides.** There is no separate lockout period to tune: an address is refused
while it holds `limit` attempts inside `window`, and it recovers as the oldest of them ages
out. One pair of numbers per budget, and "try again in eleven minutes" is a subtraction
rather than a second piece of state.

**A successful login does not clear the budget.** It is tempting — the usual reset-on-success
— and it is a bypass: an attacker holding one valid account signs into it whenever the
counter fills and carries on guessing at the others from the same address. Somebody who
signs in successfully is already through the door and does not need the budget refunded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from chainsight_web.tables import Attempt

#: What a source address is called when Starlette could not tell us one. Every such request
#: shares this single bucket, which is the conservative way round: an unidentifiable client
#: is throttled with all the other unidentifiable clients rather than exempted from counting.
UNKNOWN_CLIENT = "unknown"


@dataclass(frozen=True)
class Budget:
    """How many attempts of one kind an address may make, and over what period."""

    scope: str
    limit: int
    window: timedelta


#: Signing in, at either door. `/login` and `/admin/login` share one budget on purpose: they
#: are two forms over one credential check, and letting an attacker spend a fresh allowance
#: at the second one would make the split page a way round the limit rather than a
#: convenience.
SIGN_IN = Budget(scope="sign-in", limit=10, window=timedelta(minutes=15))

#: Creating accounts. A different budget because it is a different abuse: not guessing a
#: credential, but filling the table. The limit is lower and the window is longer, because
#: nobody legitimately opens a sixth account in an hour and somebody mistyping a password
#: ten times is ordinary.
REGISTRATION = Budget(scope="registration", limit=5, window=timedelta(hours=1))


def as_utc(moment: datetime) -> datetime:
    """The same instant, guaranteed timezone-aware. The one place two backends disagree.

    `created_at` is a `DateTime(timezone=True)` column holding an aware UTC value. Postgres
    gives it back aware. SQLite has no timestamp type and no offset in the format SQLAlchemy
    writes, so it gives it back **naive** — and subtracting a naive datetime from an aware
    one is a `TypeError`, not a wrong answer. That would mean arithmetic here worked in the
    tests and raised in a deployment, or the reverse, depending only on which database was
    behind it.

    Both values are UTC either way: `_now` writes UTC and SQLite stores exactly the digits
    it was handed. So stamping the missing offset back on is a re-labelling, not a
    conversion, and it makes this module read the same on both.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def client_address(request: Request) -> str:
    """The address this request came from, as far as the server can tell.

    Behind a reverse proxy this is only correct if the proxy's `X-Forwarded-For` is being
    honoured, which is uvicorn's `--forwarded-allow-ips` and this application's
    `CHAINSIGHT_FORWARDED_ALLOW_IPS`. Get that wrong in the permissive direction and an
    attacker sets the header themselves and gets a fresh budget per request; get it wrong in
    the strict direction and every visitor arrives as the proxy, sharing one budget, and the
    tenth wrong password locks out the whole deployment. `config.py` argues the default.
    """
    return request.client.host if request.client else UNKNOWN_CLIENT


def retry_after(
    session: Session, budget: Budget, client: str, *, now: datetime | None = None
) -> timedelta | None:
    """How long this address must wait, or `None` when it still has attempts left."""
    moment = now or datetime.now(UTC)
    since = moment - budget.window

    spent = session.scalars(
        select(Attempt.created_at)
        .where(
            Attempt.scope == budget.scope,
            Attempt.client == client,
            Attempt.created_at > since,
        )
        .order_by(Attempt.created_at)
    ).all()

    if len(spent) < budget.limit:
        return None

    # The oldest attempt still inside the window is the one whose expiry frees a slot.
    return (as_utc(spent[0]) + budget.window) - moment


def record(session: Session, budget: Budget, client: str, *, now: datetime | None = None) -> None:
    """Spend one attempt, and drop the ones that no longer count against anybody.

    Pruning here rather than on a schedule keeps this table from being the one piece of the
    application that needs a cron job. The delete is bounded by the same window the read
    uses, so a row is only removed once it can no longer affect an answer.
    """
    moment = now or datetime.now(UTC)
    session.add(Attempt(scope=budget.scope, client=client, created_at=moment))
    session.execute(
        delete(Attempt).where(
            Attempt.scope == budget.scope,
            Attempt.created_at <= moment - budget.window,
        )
    )
    session.commit()


def wait_message(remaining: timedelta) -> str:
    """What to tell somebody who has spent their budget. Says nothing about any account.

    Whether the address was guessing at a real account, a made-up one, or both is not in
    this sentence, because the whole point of `REJECTED` in `routes_auth` is that a stranger
    cannot learn which addresses have accounts. A message that leaked it only when the limit
    was hit would leak it just the same.
    """
    minutes = max(1, -(-int(remaining.total_seconds()) // 60))
    unit = "minute" if minutes == 1 else "minutes"
    return (
        f"Too many attempts from this address. Try again in about {minutes} {unit}. "
        "This limit counts attempts from where you are connecting, not from your account."
    )
