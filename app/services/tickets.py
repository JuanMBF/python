"""Ticket business logic: creation, visibility rules, workflow and comments."""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import ColumnElement, Select, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.db.types import utcnow
from app.domain.enums import EventType, TicketCategory, TicketPriority, TicketStatus
from app.domain.sla import compute_due_at
from app.domain.workflow import ACTIVE_STATUSES, FINISHED_STATUSES, can_transition
from app.models import Comment, Ticket, TicketEvent, User
from app.schemas.common import Page
from app.schemas.ticket import CommentCreate, TicketCreate, TicketRead, TicketUpdate

UNASSIGNED_LABEL = "Sin asignar"
EXPORT_LIMIT = 5000
_MAX_ID_DIGITS = 18

SortOption = Literal[
    "created_at", "-created_at", "updated_at", "-updated_at", "due_at", "-due_at", "priority", "-priority"
]

# Priorities are stored as text, so sorting by them needs an explicit rank.
_PRIORITY_RANK = case(
    {
        TicketPriority.LOW: 1,
        TicketPriority.MEDIUM: 2,
        TicketPriority.HIGH: 3,
        TicketPriority.CRITICAL: 4,
    },
    value=Ticket.priority,
)

_SORT_COLUMNS = {
    "created_at": Ticket.created_at,
    "updated_at": Ticket.updated_at,
    "due_at": Ticket.due_at,
    "priority": _PRIORITY_RANK,
}


@dataclass
class TicketFilters:
    statuses: list[TicketStatus] = field(default_factory=list)
    priorities: list[TicketPriority] = field(default_factory=list)
    categories: list[TicketCategory] = field(default_factory=list)
    assignee_id: int | None = None
    unassigned: bool = False
    overdue: bool = False
    search: str | None = None


def _base_query() -> Select[tuple[Ticket]]:
    return select(Ticket).options(selectinload(Ticket.requester), selectinload(Ticket.assignee))


def _as_ticket_id(term: str) -> int | None:
    """The ticket number a search term refers to, or None when it cannot be one."""
    # isdigit() alone also accepts characters like "²", which int() rejects; and a number with more
    # digits than a 64-bit id does not fit in an integer column.
    if term.isascii() and term.isdigit() and len(term) <= _MAX_ID_DIGITS:
        return int(term)
    return None


def _record_event(
    ticket: Ticket,
    actor: User,
    event_type: EventType,
    from_value: str | None = None,
    to_value: str | None = None,
    at: datetime | None = None,
) -> None:
    ticket.events.append(
        TicketEvent(
            actor=actor,
            event_type=event_type,
            from_value=from_value,
            to_value=to_value,
            created_at=at or utcnow(),
        )
    )


def create_ticket(db: Session, data: TicketCreate, requester: User) -> Ticket:
    now = utcnow()
    ticket = Ticket(
        title=data.title,
        description=data.description,
        category=data.category,
        priority=data.priority,
        status=TicketStatus.OPEN,
        requester=requester,
        created_at=now,
        updated_at=now,
        due_at=compute_due_at(now, data.priority),
    )
    _record_event(ticket, requester, EventType.CREATED, to_value=TicketStatus.OPEN.value, at=now)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def _filtered_query(user: User, filters: TicketFilters) -> Select[tuple[Ticket]]:
    query = _base_query()

    # Requesters can only ever see their own tickets.
    if not user.is_staff:
        query = query.where(Ticket.requester_id == user.id)

    if filters.statuses:
        query = query.where(Ticket.status.in_(filters.statuses))
    if filters.priorities:
        query = query.where(Ticket.priority.in_(filters.priorities))
    if filters.categories:
        query = query.where(Ticket.category.in_(filters.categories))
    if filters.unassigned:
        query = query.where(Ticket.assignee_id.is_(None))
    elif filters.assignee_id is not None:
        query = query.where(Ticket.assignee_id == filters.assignee_id)
    if filters.overdue:
        query = query.where(Ticket.status.in_(ACTIVE_STATUSES), Ticket.due_at < utcnow())
    if filters.search:
        term = filters.search.strip().lstrip("#")
        # autoescape: "%" and "_" in the search text are literal characters, not LIKE wildcards.
        conditions = [
            Ticket.title.icontains(term, autoescape=True),
            Ticket.description.icontains(term, autoescape=True),
        ]
        ticket_id = _as_ticket_id(term)
        if ticket_id is not None:
            conditions.append(Ticket.id == ticket_id)
        query = query.where(or_(*conditions))
    return query


def _ordering(sort: SortOption) -> tuple[ColumnElement, ColumnElement]:
    column = _SORT_COLUMNS[sort.lstrip("-")]
    return (column.desc() if sort.startswith("-") else column.asc(), Ticket.id.desc())


def list_tickets(
    db: Session,
    user: User,
    filters: TicketFilters,
    page: int = 1,
    size: int = 20,
    sort: SortOption = "-created_at",
) -> Page[TicketRead]:
    query = _filtered_query(user, filters)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    query = query.order_by(*_ordering(sort)).offset((page - 1) * size).limit(size)

    items = [TicketRead.model_validate(ticket) for ticket in db.scalars(query)]
    return Page(items=items, total=total, page=page, size=size, pages=math.ceil(total / size) if total else 0)


def export_tickets(
    db: Session, user: User, filters: TicketFilters, sort: SortOption = "-created_at"
) -> list[Ticket]:
    """Every ticket matching the filters, with the same visibility rules as the list but no pagination."""
    query = _filtered_query(user, filters).order_by(*_ordering(sort)).limit(EXPORT_LIMIT)
    return list(db.scalars(query))


def get_ticket(db: Session, ticket_id: int, user: User) -> Ticket:
    query = (
        _base_query()
        .where(Ticket.id == ticket_id)
        .options(
            selectinload(Ticket.comments).selectinload(Comment.author),
            selectinload(Ticket.events).selectinload(TicketEvent.actor),
        )
    )
    ticket = db.scalar(query)
    # Respond 404 (not 403) for other people's tickets so their existence is not leaked.
    if ticket is None or (not user.is_staff and ticket.requester_id != user.id):
        raise NotFoundError("Ticket no encontrado")
    return ticket


def update_ticket(db: Session, ticket_id: int, data: TicketUpdate, actor: User) -> Ticket:
    if not actor.is_staff:
        raise PermissionDeniedError("Solo los técnicos pueden modificar tickets")

    ticket = get_ticket(db, ticket_id, actor)
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        return ticket
    if ticket.status == TicketStatus.CLOSED:
        raise ConflictError("El ticket está cerrado y ya no se puede modificar")

    now = utcnow()

    new_status = changes.get("status")
    if new_status is not None and new_status != ticket.status:
        if not can_transition(ticket.status, new_status):
            raise ConflictError(f"Transición no permitida: '{ticket.status.value}' → '{new_status.value}'")
        _record_event(ticket, actor, EventType.STATUS_CHANGED, ticket.status.value, new_status.value, now)
        ticket.status = new_status
        if new_status in FINISHED_STATUSES:
            ticket.resolved_at = ticket.resolved_at or now
        else:
            ticket.resolved_at = None

    new_priority = changes.get("priority")
    if new_priority is not None and new_priority != ticket.priority:
        _record_event(
            ticket, actor, EventType.PRIORITY_CHANGED, ticket.priority.value, new_priority.value, now
        )
        ticket.priority = new_priority
        ticket.due_at = compute_due_at(ticket.created_at, new_priority)

    new_category = changes.get("category")
    if new_category is not None and new_category != ticket.category:
        _record_event(
            ticket, actor, EventType.CATEGORY_CHANGED, ticket.category.value, new_category.value, now
        )
        ticket.category = new_category

    if "assignee_id" in changes and changes["assignee_id"] != ticket.assignee_id:
        new_assignee = _resolve_assignee(db, changes["assignee_id"])
        _record_event(
            ticket,
            actor,
            EventType.ASSIGNED,
            ticket.assignee.full_name if ticket.assignee else UNASSIGNED_LABEL,
            new_assignee.full_name if new_assignee else UNASSIGNED_LABEL,
            now,
        )
        ticket.assignee = new_assignee

    ticket.updated_at = now
    db.commit()
    return get_ticket(db, ticket.id, actor)


def _resolve_assignee(db: Session, assignee_id: int | None) -> User | None:
    if assignee_id is None:
        return None
    assignee = db.get(User, assignee_id)
    if assignee is None or not assignee.is_active:
        raise BusinessRuleError("El técnico indicado no existe o está inactivo")
    if not assignee.is_staff:
        raise BusinessRuleError("Solo se pueden asignar tickets a técnicos o administradores")
    return assignee


def add_comment(db: Session, ticket_id: int, data: CommentCreate, author: User) -> Comment:
    ticket = get_ticket(db, ticket_id, author)

    if data.is_internal and not author.is_staff:
        raise PermissionDeniedError("Solo los técnicos pueden dejar notas internas")
    if ticket.status == TicketStatus.CLOSED:
        raise ConflictError("No se puede comentar un ticket cerrado")

    now = utcnow()
    comment = Comment(author=author, body=data.body, is_internal=data.is_internal, created_at=now)
    ticket.comments.append(comment)

    # "On hold" means waiting for the requester: their reply puts the ticket back in progress.
    if ticket.status == TicketStatus.ON_HOLD and author.id == ticket.requester_id:
        _record_event(
            ticket,
            author,
            EventType.STATUS_CHANGED,
            TicketStatus.ON_HOLD.value,
            TicketStatus.IN_PROGRESS.value,
            now,
        )
        ticket.status = TicketStatus.IN_PROGRESS

    ticket.updated_at = now
    db.commit()
    db.refresh(comment)
    return comment
