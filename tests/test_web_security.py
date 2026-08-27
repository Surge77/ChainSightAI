"""Passwords, signed cookies, and the configuration the application refuses to start without.

The bcrypt truncation test is the one worth reading. bcrypt uses the first 72 bytes of a
password and ignores the rest without complaint, so a 100-character password and its first
72 characters verify against the same hash — two different passwords opening one account.
This project refuses the long one rather than shortening it silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from itsdangerous import URLSafeTimedSerializer

from chainsight_web.config import SECRET_VAR, ConfigurationError, Settings
from chainsight_web.schemas import CostInput, OrderInput
from chainsight_web.security import (
    MAX_PASSWORD_BYTES,
    SESSION_SALT,
    PasswordError,
    hash_password,
    is_strong_enough,
    read_session,
    sign_session,
    verify_password,
)

SECRET = "a-secret-used-only-by-this-test-file"


class TestPasswords:
    def test_a_password_verifies_against_its_own_hash(self) -> None:
        stored = hash_password("a perfectly ordinary password")

        assert verify_password("a perfectly ordinary password", stored)

    def test_a_different_password_does_not(self) -> None:
        assert not verify_password("not it", hash_password("a perfectly ordinary password"))

    def test_the_same_password_hashes_differently_each_time(self) -> None:
        """The salt. Two identical passwords must not produce two identical rows."""
        first = hash_password("a perfectly ordinary password")
        second = hash_password("a perfectly ordinary password")

        assert first != second

    def test_a_password_beyond_bcrypts_limit_is_refused_rather_than_truncated(self) -> None:
        with pytest.raises(PasswordError, match="first 72 bytes"):
            hash_password("x" * (MAX_PASSWORD_BYTES + 1))

    def test_verifying_an_over_long_password_is_false_rather_than_an_error(self) -> None:
        """A login attempt is not the place to raise; it is the place to say no."""
        stored = hash_password("x" * MAX_PASSWORD_BYTES)

        assert not verify_password("x" * (MAX_PASSWORD_BYTES + 1), stored)

    def test_a_corrupted_stored_hash_refuses_the_login_rather_than_raising(self) -> None:
        """A 500 on a damaged row tells whoever is trying passwords the shape of the problem."""
        assert not verify_password("anything", "not a bcrypt hash at all")

    def test_length_is_the_only_rule(self) -> None:
        assert is_strong_enough("a long passphrase")
        assert not is_strong_enough("Passw0r!")


class TestSessions:
    def test_a_signed_cookie_round_trips(self) -> None:
        cookie = sign_session(7, secret=SECRET)

        assert read_session(cookie, secret=SECRET, max_age=3600) == 7

    def test_a_tampered_cookie_is_nobody(self) -> None:
        cookie = sign_session(7, secret=SECRET)

        assert read_session(cookie[:-4] + "aaaa", secret=SECRET, max_age=3600) is None

    def test_a_cookie_from_another_secret_is_nobody(self) -> None:
        cookie = sign_session(7, secret="a different secret entirely")

        assert read_session(cookie, secret=SECRET, max_age=3600) is None

    def test_an_expired_cookie_is_nobody(self) -> None:
        cookie = sign_session(7, secret=SECRET)

        assert read_session(cookie, secret=SECRET, max_age=-1) is None

    def test_nonsense_is_nobody(self) -> None:
        assert read_session("not even base64", secret=SECRET, max_age=3600) is None

    def test_a_correctly_signed_payload_of_the_wrong_shape_is_nobody(self) -> None:
        """Signed proves it came from us. It does not prove it is what we expect."""
        forged = URLSafeTimedSerializer(SECRET, salt=SESSION_SALT).dumps(["not", "a", "dict"])

        assert read_session(forged, secret=SECRET, max_age=3600) is None

    def test_a_signed_dict_without_an_integer_id_is_nobody(self) -> None:
        forged = URLSafeTimedSerializer(SECRET, salt=SESSION_SALT).dumps({"user_id": "1 OR 1=1"})

        assert read_session(forged, secret=SECRET, max_age=3600) is None


class TestSettings:
    def test_the_application_refuses_to_start_without_a_session_secret(self) -> None:
        """A default secret in a public repository is a forged-session vulnerability."""
        with pytest.raises(ConfigurationError, match="will not fall back"):
            Settings.from_env({})

    def test_a_blank_secret_is_refused_too(self) -> None:
        with pytest.raises(ConfigurationError, match="blank secret"):
            Settings.from_env({SECRET_VAR: "   "})

    def test_everything_else_has_a_default(self) -> None:
        settings = Settings.from_env({SECRET_VAR: SECRET})

        assert settings.host == "127.0.0.1"
        assert settings.artefacts == Path("artifacts")
        assert settings.session_seconds == 12 * 3600

    def test_the_environment_can_override_each_default(self) -> None:
        settings = Settings.from_env(
            {
                SECRET_VAR: SECRET,
                "CHAINSIGHT_DATABASE": "sqlite:///elsewhere.db",
                "CHAINSIGHT_ARTEFACTS": "/tmp/models",
                "CHAINSIGHT_DATASET": "/tmp/orders.csv",
                "CHAINSIGHT_SESSION_HOURS": "1",
                "CHAINSIGHT_HOST": "0.0.0.0",
                "CHAINSIGHT_PORT": "9001",
            }
        )

        assert settings.database_url == "sqlite:///elsewhere.db"
        assert settings.session_seconds == 3600
        assert (settings.host, settings.port) == ("0.0.0.0", 9001)

    def test_it_binds_localhost_unless_told_otherwise(self) -> None:
        """There is no TLS and no rate limiting here, and README.md says so."""
        assert Settings(session_secret=SECRET).host == "127.0.0.1"


class TestValidation:
    def test_an_order_of_zero_items_is_not_an_order(self) -> None:
        with pytest.raises(ValueError, match="quantity"):
            OrderInput(
                payment_type="DEBIT",
                category_name="Water Sports",
                customer_country="EE. UU.",
                customer_segment="Consumer",
                customer_state="IL",
                department_name="Fan Shop",
                market="USCA",
                order_country="Estados Unidos",
                order_region="South of  USA ",
                product_name="a kayak",
                shipping_mode="Standard Class",
                discount_rate=0.0,
                quantity=0,
                order_total=10.0,
                product_price=10.0,
                ordered_at="2017-01-01T00:00",  # type: ignore[arg-type]
            )

    def test_bands_that_do_not_descend_are_refused(self) -> None:
        with pytest.raises(ValueError, match="descend"):
            CostInput(
                intervention=15.0,
                margin_lost_when_late=0.5,
                fixed_penalty_when_late=25.0,
                mean_margin=0.1196,
                typical_order_value=176.88,
                critical_above=1.0,
                high_above=50.0,
                monitor_above=0.0,
            )

    def test_a_band_check_does_not_fire_when_an_earlier_field_already_failed(self) -> None:
        """Otherwise the reader gets "bands must descend" for a typo in `intervention`."""
        with pytest.raises(ValueError, match="critical_above") as raised:
            CostInput(
                intervention=15.0,
                margin_lost_when_late=0.5,
                fixed_penalty_when_late=25.0,
                mean_margin=0.1196,
                typical_order_value=176.88,
                critical_above="not a number",  # type: ignore[arg-type]
                high_above=10.0,
                monitor_above=0.0,
            )

        assert "descend" not in str(raised.value)
