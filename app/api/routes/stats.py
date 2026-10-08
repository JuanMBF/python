from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession, StaffUser
from app.schemas.stats import StatsOverview
from app.services import stats as stats_service

router = APIRouter(prefix="/stats", tags=["Métricas"])


@router.get("/overview", response_model=StatsOverview, summary="Métricas generales")
def overview(
    db: DbSession,
    _: StaffUser,
    days: Annotated[int, Query(ge=7, le=180, description="Días incluidos en la serie diaria")] = 30,
) -> StatsOverview:
    """KPIs de la mesa de ayuda: volumen, cumplimiento de SLA, tiempos y carga por técnico."""
    return stats_service.get_overview(db, days=days)
