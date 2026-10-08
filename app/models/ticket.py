from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, enum_type, utcnow
from app.domain.enums import EventType, TicketCategory, TicketPriority, TicketStatus
from app.domain.sla import is_sla_breached
from app.domain.workflow import ACTIVE_STATUSES, allowed_transitions
from app.models.user import User


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[TicketCategory] = mapped_column(enum_type(TicketCategory), index=True)
    priority: Mapped[TicketPriority] = mapped_column(enum_type(TicketPriority), index=True)
    status: Mapped[TicketStatus] = mapped_column(
        enum_type(TicketStatus), default=TicketStatus.OPEN, index=True
    )

    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="Comment.id"
    )
    events: Mapped[list["TicketEvent"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketEvent.id"
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def sla_breached(self) -> bool:
        return is_sla_breached(self.due_at, self.resolved_at, utcnow())

    @property
    def allowed_statuses(self) -> list[TicketStatus]:
        return allowed_transitions(self.status)

    def __repr__(self) -> str:
        return f"<Ticket id={self.id} status={self.status.value} priority={self.priority.value}>"


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    # Internal notes are only visible to agents and admins.
    is_internal: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()


class TicketEvent(Base):
    """Audit trail: every relevant change made to a ticket."""

    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[EventType] = mapped_column(enum_type(EventType))
    from_value: Mapped[str | None] = mapped_column(String(120))
    to_value: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="events")
    actor: Mapped[User] = relationship()
