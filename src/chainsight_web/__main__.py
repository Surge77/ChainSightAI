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

_DESCRIPTION = "Create the first administrator, or run the ChainSight application."


def init(args: argparse.Namespace) -> int:
    """Create an account, or promote an existing one to administrator."""
    app = create_app(Settings.from_env())
    password = args.password or getpass.getpass("password: ")
    if not is_strong_enough(password):
        print(f"a password needs at least {MIN_PASSWORD_LENGTH} characters", file=sys.stderr)
        return 1

    email = args.email.strip().lower()
    with app.state.sessions() as session:
        existing = session.scalars(select(User).where(User.email == email)).first()
        if existing is not None:
            existing.is_admin = args.admin
            session.commit()
            print(f"{email} already existed; is_admin is now {existing.is_admin}")
            return 0

        session.add(User(email=email, password_hash=hash_password(password), is_admin=args.admin))
        session.commit()

    print(f"created {email}{' as an administrator' if args.admin else ''}")
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

    created = subcommands.add_parser("init", help="create the first administrator")
    created.add_argument("--email", required=True)
    created.add_argument("--password", default="", help="prompted for when omitted")
    created.add_argument(
        "--operator",
        dest="admin",
        action="store_false",
        help="create an ordinary operator instead of an administrator",
    )
    created.set_defaults(run=init, admin=True)

    served = subcommands.add_parser("serve", help="run the application")
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
