from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.types import utcnow
from app.domain.enums import TicketPriority
from app.models import Ticket, User
from tests.conftest import auth

OVERVIEW = "/api/v1/stats/overview"


def test_overview_metrics(
    client: TestClient, db: Session, create_ticket, requester: User, agent: User
) -> None:
    on_time = create_ticket(requester, priority=TicketPriority.HIGH)
    late = create_ticket(requester, priority=TicketPriority.LOW)
    overdue = create_ticket(requester, priority=TicketPriority.CRITICAL)
    create_ticket(requester)  # stays open and unassigned

    for ticket_id in (on_time["id"], late["id"], overdue["id"]):
        client.patch(f"/api/v1/tickets/{ticket_id}", json={"assignee_id": agent.id}, headers=auth(agent))
    for ticket_id in (on_time["id"], late["id"]):
        client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "resolved"}, headers=auth(agent))

    # Shift timestamps so that one ticket was resolved after its SLA and another is overdue.
    now = utcnow()
    late_ticket = db.get(Ticket, late["id"])
    late_ticket.created_at = now - timedelta(hours=100)
    late_ticket.due_at = now - timedelta(hours=28)
    db.get(Ticket, overdue["id"]).due_at = now - timedelta(minutes=5)
    db.commit()

    response = client.get(OVERVIEW, headers=auth(agent))

    assert response.status_code == 200
    stats = response.json()
    assert stats["total_tickets"] == 4
    assert stats["active_tickets"] == 2
    assert stats["resolved_tickets"] == 2
    assert stats["overdue_tickets"] == 1
    assert stats["unassigned_tickets"] == 1
    assert stats["sla_compliance_rate"] == 50.0
    assert stats["avg_resolution_hours"] == 50.0
    assert stats["by_status"] == {"open": 2, "in_progress": 0, "on_hold": 0, "resolved": 2, "closed": 0}
    assert stats["active_by_priority"] == {"low": 0, "medium": 1, "high": 0, "critical": 1}
    assert len(stats["daily"]) == 30
    assert stats["daily"][-1]["created"] == 3
    assert stats["agents"] == [
        {"agent_id": agent.id, "agent_name": agent.full_name, "active": 1, "overdue": 1, "resolved": 2}
    ]


def test_overview_with_no_tickets(client: TestClient, agent: User) -> None:
    stats = client.get(OVERVIEW, params={"days": 7}, headers=auth(agent)).json()

    assert stats["total_tickets"] == 0
    assert stats["sla_compliance_rate"] is None
    assert stats["avg_resolution_hours"] is None
    assert len(stats["daily"]) == 7


def test_requesters_cannot_see_metrics(client: TestClient, requester: User) -> None:
    assert client.get(OVERVIEW, headers=auth(requester)).status_code == 403
