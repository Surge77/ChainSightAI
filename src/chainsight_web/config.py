"""Everything the application reads from its environment, and the two things it refuses.

There is no default session secret. A portfolio repository that ships one has published a
forged-session vulnerability along with the key to exploit it, and the failure mode of a
fallback is that nobody ever notices the secret was never set. So `Settings.from_env` raises
when `CHAINSIGHT_SESSION_SECRET` is absent, and the application does not start.

The second refusal is a currency this application cannot write down. `CHAINSIGHT_CURRENCY`
does have a default — the dollar the dataset is priced in — but a value outside
`chainsight.money.SYMBOLS` stops the process here rather than printing a wrong figure on
every page that shows a price. `chainsight/money.py` argues both halves of that.

Everything else has a default, because everything else is either harmless to guess or
already gitignored. The database is a file, the artefacts directory is the one the CLI
writes to, and the bind address is localhost — this app has no TLS of its own, and
`README.md` says plainly what a deployment has to put in front of it.

One of those defaults is load-bearing rather than harmless. `CHAINSIGHT_FORWARDED_ALLOW_IPS`
decides which address a request appears to come from, and the rate limiter in `throttle.py`
counts per address, so getting it wrong disables the limiter or locks out everybody. It is
argued at length beside its constant.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from chainsight.money import DEFAULT_CURRENCY, SYMBOLS, CurrencyError, resolve_currency

#: Read at startup. Absent means the process exits rather than inventing one.
SECRET_VAR = "CHAINSIGHT_SESSION_SECRET"

#: How long a signed session cookie stays valid. Short enough that a stolen cookie expires,
#: long enough that an operator working a shift is not logged out mid-order.
DEFAULT_SESSION_HOURS = 12

#: Localhost. Changing this is a deployment decision that needs the four defences
#: `SECURITY.md` lists as deliberately absent.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

#: Whose `X-Forwarded-For` uvicorn is allowed to believe. The default trusts a proxy running
#: on this machine and nobody else, which is the only safe thing to assume without knowing
#: the deployment.
#:
#: This one setting can be wrong in two directions and both are worth naming, because the
#: rate limiter in `throttle.py` counts per source address and this is what decides what a
#: source address *is*.
#:
#: Too permissive — `*` when there is no proxy in front, or one that does not overwrite the
#: header — and a client sets `X-Forwarded-For` themselves, arrives as a new address on every
#: request, and never spends a budget. The limiter is then decorative.
#:
#: Too strict — the default, behind a proxy — and every visitor arrives wearing the proxy's
#: address. They share one budget, and the tenth wrong password anybody types locks out the
#: whole deployment. That failure is at least loud.
#:
#: So `*` is correct exactly when nothing can reach the application except a proxy that sets
#: the header itself, which is true inside a container whose only ingress is the platform's.
DEFAULT_FORWARDED_ALLOW_IPS = "127.0.0.1"


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
    #: What the money on screen is labelled with. The order totals are dollars whatever this
    #: says — they come out of a fixed dataset — but the cost model is typed in by whoever
    #: runs this, and it is their currency that belongs on those fields.
    currency: str = DEFAULT_CURRENCY
    #: See `DEFAULT_FORWARDED_ALLOW_IPS`. Decides what the rate limiter counts as one client.
    forwarded_allow_ips: str = DEFAULT_FORWARDED_ALLOW_IPS

    def __post_init__(self) -> None:
        if not self.session_secret.strip():
            raise ConfigurationError(
                f"{SECRET_VAR} is empty. A blank secret signs every session with the same "
                "known key, which is the same vulnerability as having no secret at all."
            )
        if self.currency not in SYMBOLS:
            raise ConfigurationError(
                f"{self.currency!r} is not a currency this application can write down. "
                f"Supported: {', '.join(sorted(SYMBOLS))}."
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

        # Normalised and checked here rather than in `__post_init__`, so that ` eur ` from a
        # shell is accepted and a bad code arrives as the configuration error this module
        # raises rather than the `ValueError` the money table raises.
        try:
            currency = resolve_currency(source)
        except CurrencyError as refusal:
            raise ConfigurationError(str(refusal)) from refusal

        return cls(
            session_secret=secret,
            database_url=source.get("CHAINSIGHT_DATABASE", cls.database_url),
            artefacts=Path(source.get("CHAINSIGHT_ARTEFACTS", str(cls.artefacts))),
            dataset=Path(source.get("CHAINSIGHT_DATASET", str(cls.dataset))),
            session_hours=int(source.get("CHAINSIGHT_SESSION_HOURS", DEFAULT_SESSION_HOURS)),
            host=source.get("CHAINSIGHT_HOST", DEFAULT_HOST),
            port=int(source.get("CHAINSIGHT_PORT", DEFAULT_PORT)),
            currency=currency,
            forwarded_allow_ips=source.get(
                "CHAINSIGHT_FORWARDED_ALLOW_IPS", DEFAULT_FORWARDED_ALLOW_IPS
            ),
        )
