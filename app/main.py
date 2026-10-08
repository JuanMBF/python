"""FastAPI application entry point: ``uvicorn app.main:app --reload``."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text

from app import __version__
from app.api.deps import DbSession
from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import DomainError

DESCRIPTION = """
API REST para gestionar la **mesa de ayuda de soporte IT** de una organización.

* **Tickets** con prioridades, categorías y vencimiento de **SLA** calculado automáticamente.
* **Flujo de estados** validado (abierto → en progreso → resuelto → cerrado) con historial de cambios.
* **Roles**: solicitante, técnico y administrador, con autenticación **JWT**.
* **Métricas** para el panel: cumplimiento de SLA, tiempos de resolución y carga por técnico.

Para probar los endpoints protegidos usá el botón **Authorize** con un usuario demo
(por ejemplo `admin@example.com` / `Admin1234!`).
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        contact={"name": "Juan Barros", "url": "https://github.com/JuanMBF"},
        license_info={"name": "MIT"},
    )

    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    @app.get("/health", tags=["Sistema"], summary="Estado del servicio")
    def health(db: DbSession) -> dict[str, str]:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "version": __version__}

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
