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
  An administrator is made by `python -m chainsight_web init`, server-side, with no request
  involved.
- **bcrypt's 72-byte limit is refused, not absorbed.** bcrypt reads the first 72 bytes and
  ignores the rest without complaint, so a long password and its first 72 characters verify
  against the same hash — two different passwords opening one account. A longer password is
  refused rather than silently truncated.
