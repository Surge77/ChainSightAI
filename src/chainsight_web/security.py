"""Password hashing and session signing, with no web framework anywhere near either.

Both of these are small, both are easy to get subtly wrong, and both are far easier to
reason about as functions over bytes than as behaviour tangled into a request handler. So
they live here, they take and return plain values, and the FastAPI wiring that uses them is
in `dependencies.py`.

**Passwords** are bcrypt. Not a home-made hash, not a reversible encoding, and not a fast
one: bcrypt's cost parameter is the point, because a hash a GPU can compute a billion times
a second is a hash that does not protect a leaked table. bcrypt truncates silently at 72
bytes, which is a real and well-known trap — a 100-character password and its first 72
characters would verify against the same hash — so a password longer than that is refused
here rather than quietly shortened.

**Sessions** are signed cookies carrying nothing but a user id. Signed, not encrypted: the
id is not a secret, and what matters is that a browser cannot change it. The signature is
timed, so an old cookie expires without the server having to keep any session state at all.
Nothing about the user's role is in the cookie — the role is looked up from the database on
every request that needs it, because a cookie the user holds is a cookie the user can try to
edit, and the signature only proves it has not been edited *since we issued it*.
"""

from __future__ import annotations

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

#: bcrypt uses the first 72 bytes and ignores the rest, without complaint. Refusing is the
#: only honest option: silently truncating means two different passwords open one account.
MAX_PASSWORD_BYTES = 72

#: Short enough to type, long enough that a four-character password is not a login.
MIN_PASSWORD_LENGTH = 10

#: What the signed payload is namespaced under, so a cookie from one purpose cannot be
#: replayed as a cookie for another.
SESSION_SALT = "chainsight-session"

#: The cookie itself.
COOKIE_NAME = "chainsight_session"


class PasswordError(ValueError):
    """The password cannot be hashed as given."""


def hash_password(password: str) -> str:
    """A bcrypt hash, as text, ready to be stored."""
    encoded = _checked(password)
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored: str) -> bool:
    """Whether this password produced that hash.

    A malformed stored hash returns False rather than raising. A row that has somehow been
    corrupted should fail to log anybody in, which is what False does; raising would turn it
    into a 500 that leaks the shape of the problem to whoever is trying passwords.
    """
    try:
        return bcrypt.checkpw(_checked(password), stored.encode("utf-8"))
    except (PasswordError, ValueError):
        return False


def _checked(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise PasswordError(
            f"bcrypt reads only the first {MAX_PASSWORD_BYTES} bytes and ignores the rest, "
            "so a longer password is refused rather than silently truncated."
        )
    return encoded


def is_strong_enough(password: str) -> bool:
    """The one rule enforced at registration: length. Deliberately not a character policy.

    Composition rules push people towards `Passw0rd!` and away from a long passphrase, and
    the length floor is the part that actually costs an attacker time.
    """
    return len(password) >= MIN_PASSWORD_LENGTH


def _serialiser(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=SESSION_SALT)


def sign_session(user_id: int, *, secret: str) -> str:
    """The cookie value for a logged-in user. Carries an id, and nothing else."""
    return _serialiser(secret).dumps({"user_id": user_id})


def read_session(cookie: str, *, secret: str, max_age: int) -> int | None:
    """The user id inside a cookie, or `None` for anything that is not exactly that.

    Every failure — tampered, expired, truncated, from a different secret, or valid but
    carrying something other than an integer id — collapses to `None`. The caller's job is
    then simply "no user", and there is no path where a partially-trusted cookie is used.
    """
    try:
        payload = _serialiser(secret).loads(cookie, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None

    if not isinstance(payload, dict):
        return None
    user_id = payload.get("user_id")
    return user_id if isinstance(user_id, int) else None
