from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.domain.enums import TicketCategory, TicketPriority, TicketStatus
from app.models import Ticket, User
from app.schemas.common import Page
from app.schemas.ticket import (
    CommentCreate,
    CommentRead,
    TicketCreate,
    TicketDetail,
    TicketRead,
    TicketUpdate,
)
from app.services import tickets as ticket_service
from app.services.export import tickets_to_csv
from app.services.tickets import SortOption, TicketFilters

router = APIRouter(prefix="/tickets", tags=["Tickets"])


def _to_detail(ticket: Ticket, user: User) -> TicketDetail:
    detail = TicketDetail.model_validate(ticket)
    if not user.is_staff:
        detail.comments = [comment for comment in detail.comments if not comment.is_internal]
        detail.allowed_statuses = []
    return detail


def ticket_filters(
    status_: Annotated[list[TicketStatus] | None, Query(alias="status")] = None,
    priority: Annotated[list[TicketPriority] | None, Query()] = None,
    category: Annotated[list[TicketCategory] | None, Query()] = None,
    assignee_id: int | None = None,
    unassigned: bool = False,
    overdue: Annotated[bool, Query(description="Solo tickets activos con el SLA vencido")] = False,
    q: Annotated[str | None, Query(max_length=100, description="Busca en título, descripción o #id")] = None,
) -> TicketFilters:
    return TicketFilters(
        statuses=status_ or [],
        priorities=priority or [],
        categories=category or [],
        assignee_id=assignee_id,
        unassigned=unassigned,
        overdue=overdue,
        search=q,
    )


Filters = Annotated[TicketFilters, Depends(ticket_filters)]


@router.get("", response_model=Page[TicketRead], summary="Listar tickets")
def list_tickets(
    db: DbSession,
    user: CurrentUser,
    filters: Filters,
    sort: SortOption = "-created_at",
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[TicketRead]:
    """Los usuarios solicitantes solo ven sus propios tickets; los técnicos ven todos."""
    return ticket_service.list_tickets(db, user, filters, page=page, size=size, sort=sort)


@router.get(
    "/export",
    summary="Exportar tickets a CSV",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "Archivo CSV en UTF-8"}},
)
def export_tickets(
    db: DbSession, user: CurrentUser, filters: Filters, sort: SortOption = "-created_at"
) -> Response:
    """Mismos filtros y permisos que el listado, sin paginar (hasta 5.000 tickets)."""
    tickets = ticket_service.export_tickets(db, user, filters, sort=sort)
    return Response(
        content=tickets_to_csv(tickets),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tickets.csv"'},
    )


@router.post("", response_model=TicketDetail, status_code=status.HTTP_201_CREATED, summary="Crear ticket")
def create_ticket(db: DbSession, user: CurrentUser, data: TicketCreate) -> TicketDetail:
    ticket = ticket_service.create_ticket(db, data, requester=user)
    return _to_detail(ticket_service.get_ticket(db, ticket.id, user), user)


@router.get("/{ticket_id}", response_model=TicketDetail, summary="Detalle de un ticket")
def get_ticket(db: DbSession, user: CurrentUser, ticket_id: int) -> TicketDetail:
    return _to_detail(ticket_service.get_ticket(db, ticket_id, user), user)


@router.patch("/{ticket_id}", response_model=TicketDetail, summary="Actualizar ticket")
def update_ticket(db: DbSession, user: CurrentUser, ticket_id: int, data: TicketUpdate) -> TicketDetail:
    """Cambia estado, prioridad, categoría o técnico asignado. Cada cambio queda en el historial."""
    return _to_detail(ticket_service.update_ticket(db, ticket_id, data, actor=user), user)


@router.post(
    "/{ticket_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar comentario",
)
def add_comment(db: DbSession, user: CurrentUser, ticket_id: int, data: CommentCreate) -> CommentRead:
    return CommentRead.model_validate(ticket_service.add_comment(db, ticket_id, data, author=user))
