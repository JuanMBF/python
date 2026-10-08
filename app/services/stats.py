"""Aggregated metrics for the support dashboard."""

from collections import Counter
from datetime import datetime, time, timedelta
from statistics import fmean
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.types import utcnow
from app.domain.enums import TicketCategory, TicketPriority, TicketStatus, UserRole
from app.domain.workflow import ACTIVE_STATUSES, FINISHED_STATUSES
from app.models import Ticket, User
from app.schemas.stats import AgentWorkload, DailyCount, StatsOverview


def _count_by(db: Session, column: ColumnElement, *conditions: ColumnElement[bool]) -> Counter:
    query = select(column, func.count(Ticket.id)).where(*conditions).group_by(column)
    return Counter(dict(db.execute(query).all()))


def get_overview(db: Session, days: int = 30, now: datetime | None = None) -> StatsOverview:
    now = now or utcnow()
    is_active = Ticket.status.in_(ACTIVE_STATUSES)
    is_overdue = Ticket.due_at < now

    by_status = _count_by(db, Ticket.status)
    active_by_priority = _count_by(db, Ticket.priority, is_active)
    by_category = _count_by(db, Ticket.category)

    overdue = db.scalar(select(func.count(Ticket.id)).where(is_active, is_overdue)) or 0
    unassigned = db.scalar(select(func.count(Ticket.id)).where(is_active, Ticket.assignee_id.is_(None))) or 0

    # Resolution metrics are computed in Python so they work the same on every database engine.
    finished = db.execute(
        select(Ticket.created_at, Ticket.due_at, Ticket.resolved_at).where(Ticket.resolved_at.is_not(None))
    ).all()
    sla_rate = avg_hours = None
    if finished:
        on_time = sum(1 for row in finished if row.resolved_at <= row.due_at)
        sla_rate = round(100 * on_time / len(finished), 1)
        avg_hours = round(
            fmean((row.resolved_at - row.created_at).total_seconds() / 3600 for row in finished), 1
        )

    return StatsOverview(
        total_tickets=sum(by_status.values()),
        active_tickets=sum(by_status[status] for status in ACTIVE_STATUSES),
        overdue_tickets=overdue,
        unassigned_tickets=unassigned,
        resolved_tickets=sum(by_status[status] for status in FINISHED_STATUSES),
        sla_compliance_rate=sla_rate,
        avg_resolution_hours=avg_hours,
        by_status={status: by_status[status] for status in TicketStatus},
        active_by_priority={priority: active_by_priority[priority] for priority in TicketPriority},
        by_category={category: by_category[category] for category in TicketCategory},
        daily=_daily_counts(db, days, now),
        agents=_agent_workload(db, now),
    )


def _daily_counts(db: Session, days: int, now: datetime) -> list[DailyCount]:
    """Tickets created and resolved per day, bucketed in the support team's local timezone."""
    tz = ZoneInfo(settings.timezone)
    first_day = now.astimezone(tz).date() - timedelta(days=days - 1)
    since = datetime.combine(first_day, time.min, tzinfo=tz)

    created = Counter(
        value.astimezone(tz).date()
        for value in db.scalars(select(Ticket.created_at).where(Ticket.created_at >= since))
    )
    resolved = Counter(
        value.astimezone(tz).date()
        for value in db.scalars(select(Ticket.resolved_at).where(Ticket.resolved_at >= since))
    )
    return [
        DailyCount(day=day, created=created[day], resolved=resolved[day])
        for day in (first_day + timedelta(days=offset) for offset in range(days))
    ]


def _agent_workload(db: Session, now: datetime) -> list[AgentWorkload]:
    has_assignee = Ticket.assignee_id.is_not(None)
    is_active = Ticket.status.in_(ACTIVE_STATUSES)
    active = _count_by(db, Ticket.assignee_id, has_assignee, is_active)
    overdue = _count_by(db, Ticket.assignee_id, has_assignee, is_active, Ticket.due_at < now)
    resolved = _count_by(db, Ticket.assignee_id, has_assignee, Ticket.status.in_(FINISHED_STATUSES))

    # Every active agent appears (even with no tickets), plus any other user holding tickets.
    agents = db.scalars(
        select(User).where(
            or_(
                and_(User.role == UserRole.AGENT, User.is_active.is_(True)),
                User.id.in_(set(active) | set(resolved)),
            )
        )
    )
    workload = [
        AgentWorkload(
            agent_id=agent.id,
            agent_name=agent.full_name,
            active=active[agent.id],
            overdue=overdue[agent.id],
            resolved=resolved[agent.id],
        )
        for agent in agents
    ]
    return sorted(workload, key=lambda item: (-item.active, item.agent_name))
