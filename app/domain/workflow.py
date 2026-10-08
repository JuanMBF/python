"""Ticket lifecycle rules (pure Python, no database access)."""

from app.domain.enums import TicketStatus

ACTIVE_STATUSES: frozenset[TicketStatus] = frozenset(
    {TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.ON_HOLD}
)
FINISHED_STATUSES: frozenset[TicketStatus] = frozenset({TicketStatus.RESOLVED, TicketStatus.CLOSED})

ALLOWED_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.OPEN: frozenset(
        {TicketStatus.IN_PROGRESS, TicketStatus.ON_HOLD, TicketStatus.RESOLVED, TicketStatus.CLOSED}
    ),
    TicketStatus.IN_PROGRESS: frozenset({TicketStatus.OPEN, TicketStatus.ON_HOLD, TicketStatus.RESOLVED}),
    TicketStatus.ON_HOLD: frozenset({TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED}),
    # A resolved ticket is either confirmed (closed) or reopened.
    TicketStatus.RESOLVED: frozenset({TicketStatus.CLOSED, TicketStatus.IN_PROGRESS}),
    TicketStatus.CLOSED: frozenset(),
}


def can_transition(current: TicketStatus, target: TicketStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def allowed_transitions(current: TicketStatus) -> list[TicketStatus]:
    """Allowed target statuses, in the order they are declared in ``TicketStatus``."""
    return [status for status in TicketStatus if status in ALLOWED_TRANSITIONS[current]]
