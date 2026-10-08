"""Unit tests for pure business rules (no database, no HTTP)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import TicketPriority, TicketStatus
from app.domain.sla import compute_due_at, is_sla_breached
from app.domain.workflow import allowed_transitions, can_transition

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("priority", "hours"),
    [
        (TicketPriority.CRITICAL, 4),
        (TicketPriority.HIGH, 8),
        (TicketPriority.MEDIUM, 24),
        (TicketPriority.LOW, 72),
    ],
)
def test_due_date_depends_on_priority(priority: TicketPriority, hours: int) -> None:
    assert compute_due_at(NOW, priority) == NOW + timedelta(hours=hours)


def test_sla_breach_rules() -> None:
    due = NOW
    assert is_sla_breached(due, resolved_at=None, now=due + timedelta(minutes=1))
    assert not is_sla_breached(due, resolved_at=None, now=due - timedelta(minutes=1))
    assert not is_sla_breached(due, resolved_at=due - timedelta(hours=1), now=due + timedelta(days=5))
    assert is_sla_breached(due, resolved_at=due + timedelta(hours=1), now=due + timedelta(days=5))


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (TicketStatus.OPEN, TicketStatus.IN_PROGRESS, True),
        (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, True),
        (TicketStatus.RESOLVED, TicketStatus.IN_PROGRESS, True),
        (TicketStatus.ON_HOLD, TicketStatus.CLOSED, False),
        (TicketStatus.IN_PROGRESS, TicketStatus.CLOSED, False),
        (TicketStatus.CLOSED, TicketStatus.OPEN, False),
    ],
)
def test_status_transitions(current: TicketStatus, target: TicketStatus, allowed: bool) -> None:
    assert can_transition(current, target) is allowed


def test_closed_is_a_final_state() -> None:
    assert allowed_transitions(TicketStatus.CLOSED) == []
