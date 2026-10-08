from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.domain.enums import EventType, TicketCategory, TicketPriority, TicketStatus
from app.schemas.user import UserSummary

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class TicketCreate(BaseModel):
    title: Title
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=5000)]
    category: TicketCategory = TicketCategory.OTHER
    priority: TicketPriority = TicketPriority.MEDIUM


class TicketUpdate(BaseModel):
    """Partial update. Send ``assignee_id: null`` to unassign a ticket."""

    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    category: TicketCategory | None = None
    assignee_id: int | None = None


class CommentCreate(BaseModel):
    body: LongText
    is_internal: bool = False


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    body: str
    is_internal: bool
    created_at: datetime
    author: UserSummary


class TicketEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: EventType
    from_value: str | None
    to_value: str | None
    created_at: datetime
    actor: UserSummary


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    category: TicketCategory
    priority: TicketPriority
    status: TicketStatus
    created_at: datetime
    updated_at: datetime
    due_at: datetime
    resolved_at: datetime | None
    sla_breached: bool
    requester: UserSummary
    assignee: UserSummary | None


class TicketDetail(TicketRead):
    comments: list[CommentRead]
    events: list[TicketEventRead]
    allowed_statuses: list[TicketStatus]
