# 0009 — No default session secret

**Status:** accepted

## Context

The application signs session cookies. A secret has to come from somewhere, and the
convenient pattern is a default with an environment override.

## Decision

There is no default. `Settings.from_env` raises and the process does not start when
`CHAINSIGHT_SESSION_SECRET` is absent, and raises again when it is blank.

## Consequences

A default secret in a public repository is a forged-session vulnerability with the key
published beside it. Worse, the failure mode of a fallback is silence: nobody ever discovers
that the secret was never set, because everything works.

Refusing to start is loud, happens once, at the only moment anybody can act on it, and the
error message includes the command that generates a secret.

Three related choices follow the same reasoning — make the unsafe thing impossible rather than
discouraged:

- **The role is never in the cookie.** The signature proves the id has not been edited since
  it was issued; it proves nothing about what that user may do now. A role cached in a cookie
  is a role that survives being revoked, so `is_admin` is read from the database on every
  request that needs it.
- **Registration cannot grant the admin role.** There is no field for it on the form and no
  first-user-becomes-admin rule — the first is a privilege escalation, the second is a race.
  The *first* administrator is made by `python -m chainsight_web init`, server-side, with no
  request involved.
- **bcrypt's 72-byte limit is refused, not absorbed.** bcrypt reads the first 72 bytes and
  ignores the rest without complaint, so a long password and its first 72 characters verify
  against the same hash — two different passwords opening one account. A longer password is
  refused rather than silently truncated.


## Amended: an administrator may grant the role from the browser

The original wording implied something stronger than it argued for — that no UI could ever
touch a role. That is not what the reasoning supports. Both objections above are about the
role being **self-granted**: a registration checkbox lets anybody who can post a form become
an administrator, and a first-user rule is a race. Neither describes an existing
administrator promoting somebody else, which is authenticated, authorised and attributable.

Requiring a shell on the server for that is not a security property. It is a bottleneck, and
what people do about a bottleneck standing between them and a colleague who needs access is
share the admin password — which destroys attribution outright, and is strictly worse than
the thing being prevented.

So `/admin/users` lets an administrator grant and revoke the role. The invariant that
actually mattered is untouched: **nobody grants themselves the role.** What still cannot
happen there:

- **Creating an account.** No password field, because an administrator who sets somebody
  else's password knows it afterwards and every action by that account becomes deniable.
  Operators register themselves; an administrator grants the role to an account that exists.
- **Removing the last administrator.** Refused whoever asks, because the result is an
  application with no way back in short of the command line, one click away on your own row.
  Self-demotion is allowed once somebody else holds the role: the rule is about what the
  change does, not about who is asking.
- **Doing it unattributably.** Every change writes a `role_changes` row naming both parties
  in the same commit, and the page shows them. The email addresses are stored on the row
  rather than joined, so the record stays legible after an account is deleted.

**This raises the stakes of a gap `SECURITY.md` already lists.** There are no CSRF tokens,
so the defence against a forged role change is `SameSite=Lax` alone — which does stop a
cross-site form post from carrying the session, and is why this is defensible on localhost.
It is no longer merely a cost-model edit behind that gap, and the CSRF entry in `TODO.md`
now says so.
