import codecs
import csv
import io
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


@pytest.mark.parametrize("ticket_id", [10**30, -(10**30)])
def test_ids_that_do_not_fit_in_the_database_are_rejected(
    client: TestClient, create_ticket, requester, agent, ticket_id: int
) -> None:
    # They used to reach the query and blow up as a 500 (OverflowError in the driver).
    existing = create_ticket(requester)["id"]
    headers = auth(agent)

    responses = [
        client.get(f"{TICKETS}/{ticket_id}", headers=headers),
        client.patch(f"{TICKETS}/{ticket_id}", json={"priority": "high"}, headers=headers),
        client.post(f"{TICKETS}/{ticket_id}/comments", json={"body": "Hola"}, headers=headers),
        client.get(TICKETS, params={"assignee_id": ticket_id}, headers=headers),
        client.get(f"{TICKETS}/export", params={"assignee_id": ticket_id}, headers=headers),
        update(client, agent, existing, assignee_id=ticket_id),
    ]

    assert [response.status_code for response in responses] == [422] * len(responses)


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


def test_update_without_real_changes_is_not_activity(
    client: TestClient, create_ticket, requester, agent
) -> None:
    # It used to bump "updated_at", so the ticket jumped to the top of "Última actividad"
    # with nothing new in its history.
    ticket_id = create_ticket(requester, priority=TicketPriority.HIGH)["id"]
    assigned = update(client, agent, ticket_id, assignee_id=agent.id).json()

    same = update(
        client, agent, ticket_id, status="open", priority="high", category="hardware", assignee_id=agent.id
    )

    assert same.status_code == 200
    assert same.json()["updated_at"] == assigned["updated_at"]
    assert same.json()["events"] == assigned["events"]


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


@pytest.mark.parametrize("term", ["²", "9" * 30, "#" + "9" * 30])
def test_search_text_that_is_not_a_valid_ticket_number(
    client: TestClient, create_ticket, requester, agent, term: str
) -> None:
    create_ticket(requester)

    response = client.get(TICKETS, params={"q": term}, headers=auth(agent))

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_search_treats_like_wildcards_as_plain_text(
    client: TestClient, create_ticket, requester, agent
) -> None:
    discount = create_ticket(requester, title="El descuento del 100% no se aplica")
    create_ticket(requester, title="Pedido de 1000 resmas de papel")

    def ids(q: str) -> list[int]:
        response = client.get(TICKETS, params={"q": q}, headers=auth(agent))
        return [item["id"] for item in response.json()["items"]]

    assert ids("100%") == [discount["id"]]
    assert ids("_") == []


def test_search_ignores_case_of_accented_letters(client: TestClient, create_ticket, requester, agent) -> None:
    # SQLite's LOWER() only lowercases ASCII: "área" did not find "ÁREA" and "DISEÑO" did not find "diseño".
    ticket = create_ticket(requester, title="El ÁREA de diseño no tiene acceso")

    def ids(q: str) -> list[int]:
        response = client.get(TICKETS, params={"q": q}, headers=auth(agent))
        return [item["id"] for item in response.json()["items"]]

    assert ids("área") == [ticket["id"]]
    assert ids("DISEÑO") == [ticket["id"]]


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


def test_page_number_too_big_for_the_database_is_rejected(
    client: TestClient, create_ticket, requester
) -> None:
    # The offset did not fit in a 64-bit integer and the request ended in a 500 (OverflowError).
    create_ticket(requester)
    headers = auth(requester)

    assert client.get(TICKETS, params={"page": 10**30}, headers=headers).status_code == 422
    assert client.get(TICKETS, params={"page": 2**62, "size": 100}, headers=headers).status_code == 422

    last_page = client.get(TICKETS, params={"page": (2**63 - 1) // 100, "size": 100}, headers=headers)
    assert last_page.status_code == 200
    assert last_page.json()["items"] == []


# --- CSV export ---------------------------------------------------------------------------------


def export(client: TestClient, user: User, **params) -> list[dict[str, str]]:
    response = client.get(f"{TICKETS}/export", params=params, headers=auth(user))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="tickets.csv"'
    assert response.content.startswith(codecs.BOM_UTF8)  # so Excel reads the accents correctly
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_export_csv_has_one_row_per_ticket(client: TestClient, create_ticket, requester, agent) -> None:
    printer = create_ticket(requester, title="Impresora sin tóner", priority=TicketPriority.HIGH)
    vpn = create_ticket(requester, title="La VPN se desconecta", category=TicketCategory.NETWORK)
    update(client, agent, vpn["id"], status="resolved", assignee_id=agent.id)

    rows = export(client, agent)

    assert [row["id"] for row in rows] == [str(vpn["id"]), str(printer["id"])]
    assert rows[1] == {
        "id": str(printer["id"]),
        "title": "Impresora sin tóner",
        "category": "hardware",
        "priority": "high",
        "status": "open",
        "requester": "Sara Solicitante",
        "assignee": "",
        "created_at": parse(printer["created_at"]).isoformat(),
        "due_at": parse(printer["due_at"]).isoformat(),
        "resolved_at": "",
        "sla_breached": "false",
    }
    assert rows[0]["assignee"] == "Tito Técnico"
    assert rows[0]["resolved_at"] != ""


def test_export_csv_applies_filters_sort_and_visibility(
    client: TestClient, create_ticket, requester, other_requester, agent
) -> None:
    mine = create_ticket(requester, title="Impresora sin tóner", priority=TicketPriority.CRITICAL)
    theirs = create_ticket(other_requester, title="La VPN se desconecta")

    def ids(user: User, **params) -> list[int]:
        return [int(row["id"]) for row in export(client, user, **params)]

    assert ids(agent, q="vpn") == [theirs["id"]]
    assert ids(agent, priority="critical") == [mine["id"]]
    assert ids(agent, sort="created_at") == [mine["id"], theirs["id"]]
    # Requesters only get their own tickets, exactly like in the list.
    assert ids(requester) == [mine["id"]]


def test_export_csv_does_not_let_spreadsheets_run_formulas(
    client: TestClient, create_ticket, requester, agent
) -> None:
    create_ticket(requester, title='=HYPERLINK("http://example.com")')

    assert export(client, agent)[0]["title"] == '\'=HYPERLINK("http://example.com")'


def test_export_csv_requires_authentication(client: TestClient) -> None:
    assert client.get(f"{TICKETS}/export").status_code == 401
