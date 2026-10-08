"""Service Level Agreement: maximum resolution time per priority."""

from datetime import datetime, timedelta

from app.domain.enums import TicketPriority

SLA_HOURS: dict[TicketPriority, int] = {
    TicketPriority.CRITICAL: 4,
    TicketPriority.HIGH: 8,
    TicketPriority.MEDIUM: 24,
    TicketPriority.LOW: 72,
}


def compute_due_at(created_at: datetime, priority: TicketPriority) -> datetime:
    return created_at + timedelta(hours=SLA_HOURS[priority])


def is_sla_breached(due_at: datetime, resolved_at: datetime | None, now: datetime) -> bool:
    """A ticket breaches its SLA if it was resolved late, or is still unresolved past its deadline."""
    if resolved_at is not None:
        return resolved_at > due_at
    return now > due_at
