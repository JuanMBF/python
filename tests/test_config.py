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
