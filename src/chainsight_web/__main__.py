"""`python -m chainsight_web` — create the first administrator, or run the server.

Making an administrator is a command rather than a form. A "first user becomes admin" rule
is a race with anybody who can reach the port before you do, and a checkbox on the
registration page is a role the browser gets to ask for. Both are avoided by making the
only path to the admin role one that runs on the server with no request involved.

    python -m chainsight_web init --email you@example.com   # prompts for a password
    python -m chainsight_web serve
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from chainsight_web.app import create_app
from chainsight_web.config import ConfigurationError, Settings
from chainsight_web.security import MIN_PASSWORD_LENGTH, hash_password, is_strong_enough
from chainsight_web.tables import User

_DESCRIPTION = "Create the first administrator account, or start the ChainSight web app."


def _read_password(supplied: str) -> str | None:
    """The supplied password, or a prompted one; None when it is too short to accept."""
    password = supplied or getpass.getpass("password: ")
    if not is_strong_enough(password):
        print(
            f"That password is too short. It needs at least {MIN_PASSWORD_LENGTH} characters.",
            file=sys.stderr,
        )
        return None
    return password


def init(args: argparse.Namespace) -> int:
    """Create an account, promote an existing one, or reset the password on one."""
    app = create_app(Settings.from_env())
    email = args.email.strip().lower()
    # `--operator` is the only role flag, so args.admin is False when it was passed and None
    # when it was not. Creating and promoting read None as "administrator" — that is what this
    # command exists for. A reset reads it as "leave the role alone", because a role change
    # nobody typed is a role change nothing audits: `/admin/users/role` writes a `role_changes`
    # row on every web-initiated one, and a password command has no business skipping that.
    admin = True if args.admin is None else args.admin

    with app.state.sessions() as session:
        existing = session.scalars(select(User).where(User.email == email)).first()

        # The lookup happens before the password is read, and that ordering is the whole
        # point. Reading first meant an existing account was asked for a password that was
        # then dropped on the floor, under a message that read like success — so somebody
        # locked out of an account ran this, typed a new password, and believed it worked.
        if existing is not None and not args.reset_password:
            existing.is_admin = admin
            session.commit()
            print(
                f"{email} already had an account. Administrator: {existing.is_admin}. "
                "Its password was left alone — pass --reset-password if you meant to "
                "change it."
            )
            return 0

        password = _read_password(args.password)
        if password is None:
            return 1

        if existing is not None:
            existing.password_hash = hash_password(password)
            if args.admin is not None:
                existing.is_admin = args.admin
            # A password written here is one an administrator with a shell chose, and therefore
            # one they know. Holding the account at /password until the owner replaces it is
            # what keeps a reset from leaving behind a shared secret — the same hold
            # `/admin/users` puts on every password it issues, for the same reason.
            existing.must_change_password = True
            session.commit()
            print(
                f"{email} already had an account. Password reset — they will have to "
                "choose their own when they next sign in. Administrator: "
                f"{existing.is_admin}."
            )
            return 0

        session.add(User(email=email, password_hash=hash_password(password), is_admin=admin))
        session.commit()

    print(f"Created {email}{' as an administrator' if admin else ''}.")
    return 0


def serve(args: argparse.Namespace) -> int:
    """Run uvicorn against the configured host and port."""
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(
        create_app(settings),
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_level="info",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chainsight_web", description=_DESCRIPTION)
    subcommands = parser.add_subparsers(dest="command", required=True)

    created = subcommands.add_parser("init", help="create or update an account from the server")
    created.add_argument("--email", required=True)
    created.add_argument("--password", default="", help="leave it out and you will be asked for it")
    created.add_argument(
        "--reset-password",
        action="store_true",
        help="set a new password on an account that already exists, leaving its role alone",
    )
    # Defaulting to None rather than True is what lets `init` tell "no role was asked for" apart
    # from "administrator was asked for". Both create and promote treat the first as the second;
    # only a reset needs the difference, and it is the one place where getting it wrong grants a
    # role silently.
    created.add_argument(
        "--operator",
        dest="admin",
        action="store_false",
        default=None,
        help="create an ordinary account instead of an administrator",
    )
    created.set_defaults(run=init)

    served = subcommands.add_parser("serve", help="start the web app")
    served.add_argument("--host", default="")
    served.add_argument("--port", type=int, default=0)
    served.set_defaults(run=serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.run(args))
    except ConfigurationError as unstartable:
        print(unstartable, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
