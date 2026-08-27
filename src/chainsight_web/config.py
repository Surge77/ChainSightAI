"""Everything the application reads from its environment, and the one thing it refuses.

There is no default session secret. A portfolio repository that ships one has published a
forged-session vulnerability along with the key to exploit it, and the failure mode of a
fallback is that nobody ever notices the secret was never set. So `Settings.from_env` raises
when `CHAINSIGHT_SESSION_SECRET` is absent, and the application does not start.

Everything else has a default, because everything else is either harmless to guess or
already gitignored. The database is a file, the artefacts directory is the one the CLI
writes to, and the bind address is localhost — this app has no TLS and no rate limiting, and
`README.md` says plainly that it is not built to face the internet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Read at startup. Absent means the process exits rather than inventing one.
SECRET_VAR = "CHAINSIGHT_SESSION_SECRET"

#: How long a signed session cookie stays valid. Short enough that a stolen cookie expires,
#: long enough that an operator working a shift is not logged out mid-order.
DEFAULT_SESSION_HOURS = 12

#: Localhost. Changing this is a deployment decision that needs the four defences
#: `SECURITY.md` lists as deliberately absent.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


class ConfigurationError(RuntimeError):
    """The application cannot start safely with the environment it was given."""


@dataclass(frozen=True)
class Settings:
    """The configuration one process runs with."""

    session_secret: str
    database_url: str = "sqlite:///chainsight.db"
    artefacts: Path = Path("artifacts")
    #: What a retrain reads. A fixed file on the server, never anything entered through the
    #: UI — which is what keeps an operator from poisoning the training set through a form.
    dataset: Path = Path("data") / "raw" / "DataCoSupplyChainDataset.csv"
    session_hours: int = DEFAULT_SESSION_HOURS
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    def __post_init__(self) -> None:
        if not self.session_secret.strip():
            raise ConfigurationError(
                f"{SECRET_VAR} is empty. A blank secret signs every session with the same "
                "known key, which is the same vulnerability as having no secret at all."
            )

    @property
    def session_seconds(self) -> int:
        return self.session_hours * 3600

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        """Build settings from the environment, refusing to invent a session secret."""
        source = dict(os.environ if environ is None else environ)
        secret = source.get(SECRET_VAR)
        if secret is None:
            raise ConfigurationError(
                f"{SECRET_VAR} is not set. This application will not fall back to a default "
                "secret: a default in a public repository is a forged-session vulnerability "
                "with the key published beside it. Generate one with "
                '`python -c "import secrets; print(secrets.token_urlsafe(32))"`.'
            )

        return cls(
            session_secret=secret,
            database_url=source.get("CHAINSIGHT_DATABASE", cls.database_url),
            artefacts=Path(source.get("CHAINSIGHT_ARTEFACTS", str(cls.artefacts))),
            dataset=Path(source.get("CHAINSIGHT_DATASET", str(cls.dataset))),
            session_hours=int(source.get("CHAINSIGHT_SESSION_HOURS", DEFAULT_SESSION_HOURS)),
            host=source.get("CHAINSIGHT_HOST", DEFAULT_HOST),
            port=int(source.get("CHAINSIGHT_PORT", DEFAULT_PORT)),
        )
