import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_default_timezone_is_valid() -> None:
    assert Settings(_env_file=None).timezone == "America/Argentina/Buenos_Aires"


@pytest.mark.parametrize("timezone", ["Buenos Aires", "America", "", "../../etc/passwd"])
def test_unknown_timezone_fails_at_startup(timezone: str) -> None:
    # It used to be accepted and every request to /stats/overview answered 500.
    with pytest.raises(ValidationError, match="Zona horaria desconocida"):
        Settings(_env_file=None, timezone=timezone)


@pytest.mark.parametrize("rounds", [0, 3, 32])
def test_bcrypt_rounds_out_of_range_fail_at_startup(rounds: int) -> None:
    # They used to be accepted and creating a user or changing a password answered 500.
    with pytest.raises(ValidationError, match="BCRYPT_ROUNDS tiene que estar entre 4 y 31"):
        Settings(_env_file=None, bcrypt_rounds=rounds)


@pytest.mark.parametrize("minutes", [0, -5])
def test_non_positive_token_lifetime_fails_at_startup(minutes: int) -> None:
    # Tokens came out already expired: the login worked and every following request answered 401.
    with pytest.raises(ValidationError, match="ACCESS_TOKEN_EXPIRE_MINUTES tiene que ser mayor"):
        Settings(_env_file=None, access_token_expire_minutes=minutes)


def test_security_settings_limits_are_accepted() -> None:
    assert Settings(_env_file=None, bcrypt_rounds=4, access_token_expire_minutes=1).bcrypt_rounds == 4
    assert Settings(_env_file=None, bcrypt_rounds=31).bcrypt_rounds == 31
