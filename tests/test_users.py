import pytest
from fastapi.testclient import TestClient

from app.models import User
from tests.conftest import auth

USERS = "/api/v1/users"


def test_admin_creates_a_user_that_can_login(client: TestClient, admin: User) -> None:
    payload = {
        "email": "New.Tech@Example.com",
        "full_name": "  Nuevo Técnico ",
        "password": "Segura123!",
        "role": "agent",
    }

    response = client.post(USERS, json=payload, headers=auth(admin))

    assert response.status_code == 201
    created = response.json()
    assert created["email"] == "new.tech@example.com"
    assert created["full_name"] == "Nuevo Técnico"
    assert created["role"] == "agent"
    login = client.post(
        "/api/v1/auth/login", data={"username": "new.tech@example.com", "password": "Segura123!"}
    )
    assert login.status_code == 200


def test_duplicate_email_is_rejected(client: TestClient, admin: User, agent: User) -> None:
    payload = {"email": "AGENT@example.com", "full_name": "Duplicado", "password": "Segura123!"}

    assert client.post(USERS, json=payload, headers=auth(admin)).status_code == 409


def test_weak_password_is_rejected(client: TestClient, admin: User) -> None:
    payload = {"email": "x@example.com", "full_name": "Usuario", "password": "123"}

    assert client.post(USERS, json=payload, headers=auth(admin)).status_code == 422


def test_only_admins_can_manage_users(client: TestClient, agent: User, requester: User) -> None:
    payload = {"email": "x@example.com", "full_name": "Usuario", "password": "Segura123!"}

    assert client.post(USERS, json=payload, headers=auth(agent)).status_code == 403
    assert (
        client.patch(f"{USERS}/{requester.id}", json={"role": "admin"}, headers=auth(requester)).status_code
        == 403
    )
    assert client.get(USERS, headers=auth(requester)).status_code == 403


def test_agents_can_list_staff_to_assign_tickets(client: TestClient, admin, agent, requester) -> None:
    response = client.get(USERS, params={"role": ["agent", "admin"]}, headers=auth(agent))

    assert response.status_code == 200
    assert {user["email"] for user in response.json()} == {"admin@example.com", "agent@example.com"}


def test_admin_updates_role_and_deactivates_user(client: TestClient, admin: User, requester: User) -> None:
    response = client.patch(
        f"{USERS}/{requester.id}", json={"role": "agent", "is_active": False}, headers=auth(admin)
    )

    assert response.status_code == 200
    assert response.json()["role"] == "agent"
    assert response.json()["is_active"] is False


def test_admin_can_reset_a_password(client: TestClient, admin: User, requester: User) -> None:
    client.patch(f"{USERS}/{requester.id}", json={"password": "NuevaClave99"}, headers=auth(admin))

    login = client.post("/api/v1/auth/login", data={"username": requester.email, "password": "NuevaClave99"})
    assert login.status_code == 200


def test_admin_cannot_lock_themselves_out(client: TestClient, admin: User) -> None:
    deactivate = client.patch(f"{USERS}/{admin.id}", json={"is_active": False}, headers=auth(admin))
    demote = client.patch(f"{USERS}/{admin.id}", json={"role": "agent"}, headers=auth(admin))

    assert deactivate.status_code == 409
    assert demote.status_code == 409


@pytest.mark.parametrize("change", [{"role": "requester"}, {"is_active": False}])
def test_agent_with_active_tickets_cannot_be_demoted_or_deactivated(
    client: TestClient, admin: User, agent: User, requester: User, create_ticket, change: dict
) -> None:
    # Otherwise the ticket stays assigned to someone who can no longer see it nor work on it.
    ticket = create_ticket(requester)
    client.patch(f"/api/v1/tickets/{ticket['id']}", json={"assignee_id": agent.id}, headers=auth(admin))

    response = client.patch(f"{USERS}/{agent.id}", json=change, headers=auth(admin))

    assert response.status_code == 409
    assert "1 ticket activo" in response.json()["detail"]
    detail = client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth(admin)).json()
    assert detail["assignee"]["role"] == "agent"


def test_agent_whose_tickets_are_finished_can_be_deactivated(
    client: TestClient, admin: User, agent: User, requester: User, create_ticket
) -> None:
    ticket = create_ticket(requester)
    client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        json={"assignee_id": agent.id, "status": "resolved"},
        headers=auth(admin),
    )

    response = client.patch(f"{USERS}/{agent.id}", json={"is_active": False}, headers=auth(admin))

    assert response.status_code == 200


def test_update_unknown_user_returns_404(client: TestClient, admin: User) -> None:
    assert client.patch(f"{USERS}/999", json={"full_name": "Nadie"}, headers=auth(admin)).status_code == 404


def test_update_user_with_an_id_that_does_not_fit_in_the_database(client: TestClient, admin: User) -> None:
    response = client.patch(f"{USERS}/{10**30}", json={"full_name": "Nadie"}, headers=auth(admin))

    assert response.status_code == 422
