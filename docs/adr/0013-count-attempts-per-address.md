# 0013 — Count attempts per address, not per account

**Status:** accepted, closes the first item in `SECURITY.md`'s "what is not defended against"

## Context

`SECURITY.md` has said this since the web application landed:

> **No brute-force lockout on login.** Nothing counts failed attempts or delays a repeat, so
> an attacker with a candidate list is limited only by bcrypt's own cost.

That was an honest thing to publish while the application bound to `127.0.0.1` and the README
said it was not built to face the internet. It stops being acceptable the moment a deployment
puts `/login` on a public address, which is what deploying this as a demo does.

`TODO.md` recorded it as "Login rate limiting and account lockout" — and the second half of
that phrase is the decision this file exists to argue with.

## Decision

Count attempts against the **source address**, in a sliding window, and refuse while the
count is at the limit. Two budgets: signing in (10 in 15 minutes, shared by `/login` and
`/admin/login`) and registering (5 in an hour). Rows live in an `attempts` table and are
pruned by the write that adds to them.

**Not per account.** Locking an account after N wrong passwords is the familiar design, and
it hands anybody on the internet a way to lock anybody else out by typing rubbish at their
email address. That is a denial of service introduced to fix a brute force, and on a system
with no account-recovery flow — this one — the lockout has no exit.

Per-address is also strictly stronger against the attacker `SECURITY.md` actually named. One
source trying many passwords at one account and one source trying one password at many
accounts land in the same bucket, because the bucket is the source. A per-account counter
catches only the first shape.

## Consequences

**What it buys.** An address gets ten guesses a quarter of an hour. bcrypt already makes each
guess slow; this makes the eleventh impossible rather than merely expensive. Registration
floods — the abuse that matters on a public demo with a free-tier database behind it — are
capped by the same mechanism with different numbers.

**What it costs, stated rather than discovered.** An attacker distributing one candidate list
across many source addresses is not slowed by this at all. Closing that needs per-account
counting, which needs an answer to the lockout-as-denial-of-service problem above. Neither is
here, and `SECURITY.md` now says so in those words rather than claiming the gap is shut.

**The load-bearing setting.** Per-address counting is only as good as the address. Behind a
reverse proxy, `request.client.host` is the proxy unless its forwarding header is honoured, so
`CHAINSIGHT_FORWARDED_ALLOW_IPS` decides what a client *is*. Too permissive and a client
forges the header and never spends a budget; too strict and every visitor shares the proxy's
address, so the tenth wrong password anybody types locks out the deployment. The default
trusts only a proxy on the same machine. `config.py` argues both directions beside the
constant.

**A successful sign-in does not refund the budget.** The usual reset-on-success is a bypass:
an attacker holding one working account signs into it whenever the counter fills and carries
on guessing at the others from the same address. Somebody who has just signed in is through
the door and does not need the allowance back.

**The refusal names no account.** `routes_auth` answers a wrong password and an address with
no account with one sentence, precisely so a stranger cannot learn which addresses have
accounts. A limit message that leaked it only at the eleventh attempt would leak it just the
same, so the wait message says the limit is on the address and nothing else.

**No new dependency, and no scheduled job.** The table is SQLAlchemy like everything else, and
`throttle.record` deletes rows that have aged out of the window as it writes. A cleanup cron
would be the only piece of this application that needed somewhere to run.
