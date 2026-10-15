from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.models import User
from tests.conftest import PASSWORD, auth


def login(client: TestClient, email: str, password: str):
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


def test_login_returns_a_token_that_identifies_the_user(client: TestClient, agent: User) -> None:
    response = login(client, "agent@example.com", PASSWORD)

    assert response.status_code == 200
    token = response.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "agent@example.com"
    assert me.json()["role"] == "agent"
    assert "hashed_password" not in me.json()


def test_login_email_is_case_insensitive(client: TestClient, agent: User) -> None:
    assert login(client, "AGENT@Example.com", PASSWORD).status_code == 200


def test_login_ignores_spaces_around_the_email(client: TestClient, agent: User) -> None:
    # Creating a user with " agent@example.com " stores it trimmed, so logging in with it must work too.
    assert login(client, " agent@example.com\t", PASSWORD).status_code == 200


def test_login_with_wrong_password_fails(client: TestClient, agent: User) -> None:
    response = login(client, "agent@example.com", "wrong-password")

    assert response.status_code == 401
    assert response.json()["detail"] == "Email o contraseña incorrectos"


def test_login_with_unknown_email_fails(client: TestClient) -> None:
    assert login(client, "nobody@example.com", PASSWORD).status_code == 401


def test_inactive_user_cannot_login(client: TestClient, make_user) -> None:
    make_user(email="gone@example.com", is_active=False)

    assert login(client, "gone@example.com", PASSWORD).status_code == 403


def test_protected_endpoint_requires_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


def test_invalid_and_expired_tokens_are_rejected(client: TestClient, agent: User) -> None:
    expired = create_access_token(agent.id, expires_minutes=-1)

    for token in ("not-a-jwt", expired):
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401


def test_token_of_a_deactivated_user_stops_working(client: TestClient, db, agent: User) -> None:
    headers = auth(agent)
    agent.is_active = False
    db.commit()

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
