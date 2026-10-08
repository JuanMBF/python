from datetime import date

from pydantic import BaseModel

from app.domain.enums import TicketCategory, TicketPriority, TicketStatus


class DailyCount(BaseModel):
    day: date
    created: int
    resolved: int


class AgentWorkload(BaseModel):
    agent_id: int
    agent_name: str
    active: int
    overdue: int
    resolved: int


class StatsOverview(BaseModel):
    total_tickets: int
    active_tickets: int
    overdue_tickets: int
    unassigned_tickets: int
    resolved_tickets: int
    sla_compliance_rate: float | None
    avg_resolution_hours: float | None
    by_status: dict[TicketStatus, int]
    active_by_priority: dict[TicketPriority, int]
    by_category: dict[TicketCategory, int]
    daily: list[DailyCount]
    agents: list[AgentWorkload]
