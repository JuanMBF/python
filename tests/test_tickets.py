from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import TicketCategory, TicketPriority, UserRole
from app.models import Ticket, User
from tests.conftest import auth

TICKETS = "/api/v1/tickets"


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def update(client: TestClient, user: User, ticket_id: int, **changes):
    return client.patch(f"{TICKETS}/{ticket_id}", json=changes, headers=auth(user))


# --- Creation -----------------------------------------------------------------------------------


def test_create_ticket_sets_requester_status_and_sla(create_ticket, requester: User) -> None:
    ticket = create_ticket(requester, priority=TicketPriority.HIGH)

    assert ticket["status"] == "open"
    assert ticket["requester"]["id"] == requester.id
    assert ticket["assignee"] is None
    assert parse(ticket["due_at"]) - parse(ticket["created_at"]) == timedelta(hours=8)
    assert ticket["sla_breached"] is False
    assert [event["event_type"] for event in ticket["events"]] == ["created"]


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Hola", "description": "Descripción suficientemente larga"},  # title too short
        {"title": "Título válido", "description": "corta"},  # description too short
        {"title": "Título válido", "description": "Descripción larga", "priority": "urgent"},
    ],
)
def test_create_ticket_validates_input(client: TestClient, requester: User, payload: dict) -> None:
    assert client.post(TICKETS, json=payload, headers=auth(requester)).status_code == 422


# --- Visibility ---------------------------------------------------------------------------------


def test_requesters_only_see_their_own_tickets(
    client: TestClient, create_ticket, requester: User, other_requester: User, agent: User
) -> None:
    mine = create_ticket(requester)
    theirs = create_ticket(other_requester)

    listed = client.get(TICKETS, headers=auth(requester)).json()
    assert [item["id"] for item in listed["items"]] == [mine["id"]]
    assert client.get(f"{TICKETS}/{theirs['id']}", headers=auth(requester)).status_code == 404

    staff_view = client.get(TICKETS, headers=auth(agent)).json()
    assert staff_view["total"] == 2


def test_unknown_ticket_returns_404(client: TestClient, agent: User) -> None:
    assert client.get(f"{TICKETS}/999", headers=auth(agent)).status_code == 404


# --- Workflow -----------------------------------------------------------------------------------


def test_agent_moves_ticket_through_its_lifecycle(
    client: TestClient, create_ticket, requester, agent
) -> None:
    ticket_id = create_ticket(requester)["id"]

    in_progress = update(client, agent, ticket_id, status="in_progress", assignee_id=agent.id).json()
    assert in_progress["status"] == "in_progress"
    assert in_progress["assignee"]["id"] == agent.id

    resolved = update(client, agent, ticket_id, status="resolved").json()
    assert resolved["resolved_at"] is not None
    assert resolved["allowed_statuses"] == ["in_progress", "closed"]

    closed = update(client, agent, ticket_id, status="closed").json()
    assert closed["status"] == "closed"
    assert closed["allowed_statuses"] == []
    # Closing keeps the original resolution date.
    assert closed["resolved_at"] == resolved["resolved_at"]

    history = [(e["event_type"], e["from_value"], e["to_value"]) for e in closed["events"]]
    assert history == [
        ("created", None, "open"),
        ("status_changed", "open", "in_progress"),
        ("assigned", "Sin asignar", "Tito Técnico"),
        ("status_changed", "in_progress", "resolved"),
        ("status_changed", "resolved", "closed"),
    ]


def test_invalid_status_transition_is_rejected(client: TestClient, create_ticket, requester, agent) -> None:
    ticket_id = create_ticket(requester)["id"]
    update(client, agent, ticket_id, status="on_hold")

    response = update(client, agent, ticket_id, status="closed")

    assert response.status_code == 409
    assert "Transición no permitida" in response.json()["detail"]


def test_closed_tickets_cannot_be_modified(client: TestClient, create_ticket, requester, agent) -> None:
    ticket_id = create_ticket(requester)["id"]
    update(client, agent, ticket_id, status="closed")

    assert update(client, agent, ticket_id, priority="low").status_code == 409


def test_reopening_a_resolved_ticket_clears_resolution_date(
    client: TestClient, create_ticket, requester, agent
) -> None:
    ticket_id = create_ticket(requester)["id"]
    update(client, agent, ticket_id, status="resolved")

    reopened = update(client, agent, ticket_id, status="in_progress").json()

    assert reopened["status"] == "in_progress"
    assert reopened["resolved_at"] is None


def test_requesters_cannot_update_tickets(client: TestClient, create_ticket, requester) -> None:
    ticket_id = create_ticket(requester)["id"]

    assert update(client, requester, ticket_id, status="closed").status_code == 403


def test_changing_priority_recalculates_sla(client: TestClient, create_ticket, requester, agent) -> None:
    ticket = create_ticket(requester, priority=TicketPriority.LOW)

    updated = update(client, agent, ticket["id"], priority="critical").json()

    assert parse(updated["due_at"]) - parse(updated["created_at"]) == timedelta(hours=4)
    assert updated["events"][-1]["event_type"] == "priority_changed"


def test_tickets_can_only_be_assigned_to_active_staff(
    client: TestClient, create_ticket, make_user, requester, agent
) -> None:
    ticket_id = create_ticket(requester)["id"]
    inactive_agent = make_user(UserRole.AGENT, is_active=False)

    assert update(client, agent, ticket_id, assignee_id=requester.id).status_code == 422
    assert update(client, agent, ticket_id, assignee_id=inactive_agent.id).status_code == 422
    assert update(client, agent, ticket_id, assignee_id=12345).status_code == 422


def test_ticket_can_be_unassigned(client: TestClient, create_ticket, requester, agent) -> None:
    ticket_id = create_ticket(requester)["id"]
    update(client, agent, ticket_id, assignee_id=agent.id)

    unassigned = update(client, agent, ticket_id, assignee_id=None).json()

    assert unassigned["assignee"] is None
    assert unassigned["events"][-1]["to_value"] == "Sin asignar"


# --- Comments -----------------------------------------------------------------------------------


def test_internal_notes_are_hidden_from_requesters(
    client: TestClient, create_ticket, requester, agent
) -> None:
    ticket_id = create_ticket(requester)["id"]
    comments = f"{TICKETS}/{ticket_id}/comments"
    client.post(comments, json={"body": "Ya lo estoy revisando"}, headers=auth(agent))
    client.post(comments, json={"body": "Escalar a proveedor", "is_internal": True}, headers=auth(agent))

    as_requester = client.get(f"{TICKETS}/{ticket_id}", headers=auth(requester)).json()
    as_agent = client.get(f"{TICKETS}/{ticket_id}", headers=auth(agent)).json()

    assert [c["body"] for c in as_requester["comments"]] == ["Ya lo estoy revisando"]
    assert len(as_agent["comments"]) == 2


def test_requesters_cannot_write_internal_notes(client: TestClient, create_ticket, requester) -> None:
    ticket_id = create_ticket(requester)["id"]

    response = client.post(
        f"{TICKETS}/{ticket_id}/comments", json={"body": "Hola", "is_internal": True}, headers=auth(requester)
    )

    assert response.status_code == 403


def test_requester_cannot_comment_on_someone_elses_ticket(
    client: TestClient, create_ticket, requester, other_requester
) -> None:
    ticket_id = create_ticket(other_requester)["id"]

    response = client.post(f"{TICKETS}/{ticket_id}/comments", json={"body": "Hola"}, headers=auth(requester))

    assert response.status_code == 404


def test_requester_reply_resumes_a_ticket_on_hold(
    client: TestClient, create_ticket, requester, agent
) -> None:
    ticket_id = create_ticket(requester)["id"]
    update(client, agent, ticket_id, status="on_hold")

    client.post(
        f"{TICKETS}/{ticket_id}/comments", json={"body": "Ya probé y sigue igual"}, headers=auth(requester)
    )

    ticket = client.get(f"{TICKETS}/{ticket_id}", headers=auth(agent)).json()
    assert ticket["status"] == "in_progress"
    assert ticket["events"][-1]["actor"]["id"] == requester.id


def test_closed_tickets_do_not_accept_comments(client: TestClient, create_ticket, requester, agent) -> None:
    ticket_id = create_ticket(requester)["id"]
    update(client, agent, ticket_id, status="closed")

    response = client.post(f"{TICKETS}/{ticket_id}/comments", json={"body": "Hola"}, headers=auth(agent))

    assert response.status_code == 409


# --- Listing, filters and pagination ------------------------------------------------------------


def test_list_filters(client: TestClient, create_ticket, requester, agent) -> None:
    printer = create_ticket(requester, title="Impresora sin tóner", category=TicketCategory.HARDWARE)
    vpn = create_ticket(
        requester, title="La VPN se desconecta", category=TicketCategory.NETWORK, priority=TicketPriority.HIGH
    )
    update(client, agent, vpn["id"], status="in_progress", assignee_id=agent.id)

    def ids(**params) -> list[int]:
        response = client.get(TICKETS, params=params, headers=auth(agent))
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()["items"]]

    assert ids(status="in_progress") == [vpn["id"]]
    assert ids(status=["open", "in_progress"]) == [vpn["id"], printer["id"]]
    assert ids(category="hardware") == [printer["id"]]
    assert ids(priority="high") == [vpn["id"]]
    assert ids(assignee_id=agent.id) == [vpn["id"]]
    assert ids(unassigned=True) == [printer["id"]]
    assert ids(q="vpn") == [vpn["id"]]
    assert ids(q=f"#{printer['id']}") == [printer["id"]]


def test_overdue_filter_and_sla_flag(
    client: TestClient, db: Session, create_ticket, requester, agent
) -> None:
    late = create_ticket(requester, title="Ticket atrasado")
    create_ticket(requester, title="Ticket en término")
    ticket = db.get(Ticket, late["id"])
    ticket.due_at = ticket.created_at - timedelta(hours=1)
    db.commit()

    response = client.get(TICKETS, params={"overdue": True}, headers=auth(agent)).json()

    assert [item["id"] for item in response["items"]] == [late["id"]]
    assert response["items"][0]["sla_breached"] is True


def test_sort_by_priority(client: TestClient, create_ticket, requester, agent) -> None:
    for priority in (TicketPriority.MEDIUM, TicketPriority.CRITICAL, TicketPriority.LOW):
        create_ticket(requester, priority=priority)

    items = client.get(TICKETS, params={"sort": "-priority"}, headers=auth(agent)).json()["items"]

    assert [item["priority"] for item in items] == ["critical", "medium", "low"]


def test_pagination(client: TestClient, create_ticket, requester) -> None:
    for number in range(5):
        create_ticket(requester, title=f"Ticket número {number}")

    page = client.get(TICKETS, params={"page": 2, "size": 2}, headers=auth(requester)).json()

    assert page["total"] == 5
    assert page["pages"] == 3
    assert [item["title"] for item in page["items"]] == ["Ticket número 2", "Ticket número 1"]
