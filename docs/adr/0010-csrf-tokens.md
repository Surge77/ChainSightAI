# 0010 — CSRF tokens, checked globally rather than per route

**Status:** accepted

## Context

Every state-changing action in this application is a form post carrying a session cookie.
Nothing stopped another site from causing that post: `SameSite=Lax` prevents a cross-site
form submission from carrying the cookie, which is real protection, but it is a browser
default rather than something this application does, and it is one setting away from being
untrue.

`SECURITY.md` listed the gap from the start. What made it urgent was moving role management
into the UI (ADR 0009's amendment). The most valuable request behind the gap stopped being
"edit the cost model" and became `POST /admin/users/role` — a request that grants
administrator.

## Decision

Double-submit tokens, and the check is registered **on the application**, not on the routes
that need it:

```python
app = FastAPI(..., dependencies=[Depends(verify_csrf)])
```

A random token lives in its own `HttpOnly` cookie, the same value is rendered into every
form, and an unsafe method whose form field does not match the cookie is refused with 403.
Safe methods skip the check entirely. `templating.render` mints the token, sets the cookie
and puts the value in the context, so a page cannot be rendered without one.

## Consequences

**Global, because a per-route list is a thing somebody forgets.** A route-level dependency
protects the routes somebody remembered to decorate, and the failure mode of forgetting is
silent — the route works perfectly and is simply unprotected. Registered on the application
it fails closed: a new form without a token is a 403 on a page that used to work, which is
loud, immediate, and harmless. `tests/test_web_csrf.py` posts to every state-changing route
without a token and requires all of them to refuse.

**The token is `HttpOnly`.** Double-submit schemes often expose the cookie so that
JavaScript can copy it into a header. Nothing here does that — the server renders the value
straight into the HTML — so the cookie can stay unreadable to scripts, and an XSS that would
otherwise hand an attacker a matching pair does not.

**It rotates when a session starts.** Carrying a token across a login would let one an
attacker had already fixed in the browser keep working against the account that has just
signed in, which is the CSRF half of session fixation.

**It does not rotate per render.** A page can be open in two tabs, and a fresh token each
time would break whichever form was not submitted last.

**A template scan is part of the suite.** `test_every_post_form_carries_a_token` counts
`<form method="post">` against `name="csrf_token"` in every template, so a form added without
one is a build failure rather than a 403 somebody reports later.

**The tests needed a browser, not a client.** Every form the application renders carries the
token, so a test posting without one tests a submission no browser makes. `conftest`'s
`BrowserClient` fills the field in exactly where the rendered HTML would have; `raw_client`
does not, and the tests about CSRF use it.

This closes the first of the four items `SECURITY.md` has listed as deliberately absent
since phase 0.
