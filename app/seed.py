"""Applies database migrations and loads realistic demo data.

Usage:
    python -m app.seed            # migrate + seed only if the database is empty
    python -m app.seed --reset    # wipe everything and seed again
"""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.domain.enums import EventType, TicketCategory, TicketPriority, TicketStatus, UserRole
from app.domain.sla import SLA_HOURS, compute_due_at
from app.models import Comment, Ticket, TicketEvent, User

ROOT_DIR = Path(__file__).resolve().parent.parent

DEMO_PASSWORD = "Demo1234!"
ADMIN = ("admin@example.com", "Admin HelpDesk", "Admin1234!")
AGENTS = [
    ("lucia.fernandez@example.com", "Lucía Fernández"),
    ("martin.gomez@example.com", "Martín Gómez"),
    ("sofia.ramirez@example.com", "Sofía Ramírez"),
]
REQUESTERS = [
    ("valentina.lopez@example.com", "Valentina López"),
    ("tomas.herrera@example.com", "Tomás Herrera"),
    ("camila.torres@example.com", "Camila Torres"),
    ("nicolas.diaz@example.com", "Nicolás Díaz"),
    ("florencia.castro@example.com", "Florencia Castro"),
    ("agustin.romero@example.com", "Agustín Romero"),
    ("julieta.morales@example.com", "Julieta Morales"),
    ("matias.silva@example.com", "Matías Silva"),
]

TICKET_TEMPLATES: dict[TicketCategory, list[tuple[str, str]]] = {
    TicketCategory.HARDWARE: [
        (
            "La impresora del segundo piso no imprime",
            "Aparece 'atasco de papel' pero no hay ninguna hoja trabada. Ya la apagué y prendí.",
        ),
        (
            "El monitor parpadea constantemente",
            "Desde esta mañana el monitor se apaga y prende cada pocos segundos. Ya probé otro cable.",
        ),
        (
            "La notebook no enciende",
            "Presiono el botón de encendido y solo se prende una luz naranja. Ayer funcionaba bien.",
        ),
        (
            "Teclado con teclas que no responden",
            "Las teclas A, S y D no escriben. Necesito un reemplazo para seguir trabajando.",
        ),
        (
            "Solicitud de segundo monitor",
            "Para el puesto de análisis necesitaría un segundo monitor de 24 pulgadas.",
        ),
    ],
    TicketCategory.SOFTWARE: [
        (
            "Error al abrir Excel con macros",
            "Al abrir el reporte mensual aparece 'Las macros están deshabilitadas' y no puedo habilitarlas.",
        ),
        (
            "Falla la actualización de Windows",
            "La actualización se queda en 35% y después revierte los cambios. Ya lo intenté tres veces.",
        ),
        (
            "Instalar Visual Studio Code",
            "Necesito Visual Studio Code y Git instalados para el nuevo proyecto del área.",
        ),
        (
            "El sistema de facturación se cierra solo",
            "Cuando intento emitir una factura tipo A el sistema se cierra sin mostrar ningún error.",
        ),
        (
            "Sin audio en las videollamadas de Teams",
            "En las reuniones de Teams no escucho a nadie, aunque el audio de la PC funciona bien.",
        ),
        (
            "La licencia de Office está vencida",
            "Word y Excel muestran 'Producto sin licencia' y no me dejan editar documentos.",
        ),
    ],
    TicketCategory.NETWORK: [
        (
            "Sin conexión a internet en la oficina 3",
            "Ninguna de las PCs de la oficina 3 tiene internet desde las 9 de la mañana.",
        ),
        (
            "La VPN se desconecta cada 10 minutos",
            "Trabajando desde casa, la VPN se corta seguido y pierdo lo que estoy cargando en el sistema.",
        ),
        (
            "WiFi muy lento en la sala de reuniones",
            "En la sala de reuniones grande el WiFi es muy lento y se cortan las videollamadas.",
        ),
        (
            "No puedo acceder a la carpeta compartida",
            "Al entrar a \\\\servidor\\administracion me dice 'Acceso denegado'. La semana pasada entraba.",
        ),
    ],
    TicketCategory.ACCESS: [
        ("Blanqueo de contraseña", "Olvidé mi contraseña de dominio y no puedo iniciar sesión en la PC."),
        (
            "Alta de usuario para nuevo ingreso",
            "El lunes ingresa una persona al área de Compras. Necesita usuario, correo y acceso al ERP.",
        ),
        (
            "Permisos para la carpeta de Finanzas",
            "Necesito permisos de lectura sobre la carpeta de Finanzas para armar el presupuesto anual.",
        ),
        (
            "Cuenta bloqueada por intentos fallidos",
            "Mi cuenta quedó bloqueada después de varios intentos con la contraseña vieja.",
        ),
    ],
    TicketCategory.EMAIL: [
        ("No recibo correos externos", "Desde ayer no me llegan correos de clientes, solo los internos."),
        ("Outlook no sincroniza", "Outlook queda en 'Intentando conectar...' y no descarga mensajes nuevos."),
        (
            "Configurar la firma institucional",
            "Necesito configurar la nueva firma institucional en Outlook y en el celular.",
        ),
        (
            "Correo sospechoso de phishing",
            "Recibí un correo que dice ser del banco pidiendo mis datos. No hice clic en nada.",
        ),
    ],
    TicketCategory.OTHER: [
        (
            "Préstamo de proyector para capacitación",
            "El jueves damos una capacitación en el auditorio y necesitamos un proyector.",
        ),
        (
            "Consulta sobre el uso de OneDrive",
            "¿Cómo puedo compartir una carpeta de OneDrive con alguien de otra área?",
        ),
        (
            "Soporte para evento por videoconferencia",
            "El viernes hay una charla híbrida y necesitamos asistencia con la cámara y el audio.",
        ),
    ],
}

AGENT_REPLIES = [
    "Hola, ya estoy revisando el caso. Te aviso apenas tenga novedades.",
    "¿Me podrías indicar el número de inventario del equipo?",
    "Me conecté de forma remota y estoy aplicando la solución.",
    "Paso por tu puesto en unos minutos para revisarlo.",
]
AGENT_RESOLUTIONS = [
    "Listo, se reinstaló el driver y quedó funcionando. ¿Lo podés confirmar?",
    "Quedó resuelto. Era un problema de configuración del perfil.",
    "Se aplicó la solución y lo probamos juntos. Cierro el caso si no hay novedades.",
    "Ya tenés los accesos solicitados. Cualquier cosa nos avisás.",
]
REQUESTER_REPLIES = [
    "Gracias, quedo atento.",
    "Sigue pasando lo mismo, lo acabo de probar.",
    "El número de inventario es NB-{n:04d}.",
    "Perfecto, ya funciona. ¡Muchas gracias!",
]
INTERNAL_NOTES = [
    "Si persiste, escalar al proveedor del equipo.",
    "Es el tercer caso igual esta semana: revisar la política de GPO.",
    "Pendiente de compra del repuesto, el pedido ya está hecho.",
]


def _resolution_time(rng: random.Random, sla: timedelta) -> timedelta:
    """Most tickets are solved well within the SLA; roughly 1 in 10 runs late."""
    return sla * max(0.1, rng.betavariate(2, 5) * 2)


def run_migrations() -> None:
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    command.upgrade(config, "head")


def reset_database() -> None:
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def _event(
    ticket: Ticket, actor: User, kind: EventType, old: str | None, new: str | None, at: datetime
) -> None:
    ticket.events.append(
        TicketEvent(actor=actor, event_type=kind, from_value=old, to_value=new, created_at=at)
    )


def _comment(ticket: Ticket, author: User, body: str, at: datetime, internal: bool = False) -> None:
    ticket.comments.append(Comment(author=author, body=body, is_internal=internal, created_at=at))


def _pick_priority(rng: random.Random) -> TicketPriority:
    return rng.choices(
        [TicketPriority.LOW, TicketPriority.MEDIUM, TicketPriority.HIGH, TicketPriority.CRITICAL],
        weights=[25, 45, 22, 8],
    )[0]


def _build_ticket(
    rng: random.Random, now: datetime, requester: User, agents: list[User], age: timedelta
) -> Ticket:
    category = rng.choice(list(TICKET_TEMPLATES))
    title, description = rng.choice(TICKET_TEMPLATES[category])
    priority = _pick_priority(rng)
    created_at = now - age
    ticket = Ticket(
        title=title,
        description=description,
        category=category,
        priority=priority,
        status=TicketStatus.OPEN,
        requester=requester,
        created_at=created_at,
        updated_at=created_at,
        due_at=compute_due_at(created_at, priority),
    )
    _event(ticket, requester, EventType.CREATED, None, TicketStatus.OPEN.value, created_at)

    sla = timedelta(hours=SLA_HOURS[priority])
    resolve_after = _resolution_time(rng, sla)
    # A ticket is finished once its resolution time has elapsed (a few stay stuck, as in real life).
    if resolve_after < age and rng.random() < 0.96:
        outcome = "finished"
    elif age < timedelta(hours=3) or rng.random() < 0.15:
        return ticket  # brand new, nobody picked it up yet
    else:
        outcome = rng.choice(["in_progress", "in_progress", "on_hold"])
        resolve_after = min(resolve_after, age)

    agent = rng.choice(agents)
    pickup_at = created_at + min(resolve_after * 0.2, timedelta(hours=2))

    _event(ticket, agent, EventType.ASSIGNED, "Sin asignar", agent.full_name, pickup_at)
    _event(ticket, agent, EventType.STATUS_CHANGED, "open", "in_progress", pickup_at)
    ticket.assignee = agent
    ticket.status = TicketStatus.IN_PROGRESS
    _comment(ticket, agent, rng.choice(AGENT_REPLIES), pickup_at + timedelta(minutes=5))
    if rng.random() < 0.5:
        reply = rng.choice(REQUESTER_REPLIES[:3]).format(n=rng.randint(1, 9999))
        _comment(ticket, requester, reply, pickup_at + timedelta(minutes=rng.randint(10, 90)))
    if rng.random() < 0.25:
        _comment(ticket, agent, rng.choice(INTERNAL_NOTES), pickup_at + timedelta(minutes=95), internal=True)

    last_change = pickup_at + timedelta(minutes=100)
    if outcome == "on_hold":
        _event(ticket, agent, EventType.STATUS_CHANGED, "in_progress", "on_hold", last_change)
        ticket.status = TicketStatus.ON_HOLD
    elif outcome == "finished":
        resolved_at = max(created_at + resolve_after, last_change)
        _comment(ticket, agent, rng.choice(AGENT_RESOLUTIONS), resolved_at)
        _event(ticket, agent, EventType.STATUS_CHANGED, "in_progress", "resolved", resolved_at)
        ticket.status = TicketStatus.RESOLVED
        ticket.resolved_at = resolved_at
        last_change = resolved_at
        if now - resolved_at > timedelta(days=2) and rng.random() < 0.8:
            closed_at = resolved_at + timedelta(days=1)
            _comment(ticket, requester, REQUESTER_REPLIES[3], closed_at - timedelta(hours=2))
            _event(ticket, agent, EventType.STATUS_CHANGED, "resolved", "closed", closed_at)
            ticket.status = TicketStatus.CLOSED
            last_change = closed_at

    # Very recent tickets could get activity "in the future": clamp it (keeps chronological order).
    for item in (*ticket.events, *ticket.comments):
        item.created_at = min(item.created_at, now)
    ticket.updated_at = min(last_change, now)
    return ticket


def seed_demo_data(db: Session, ticket_count: int = 360, days: int = 45, seed: int = 42) -> None:
    rng = random.Random(seed)
    now = utcnow()

    demo_hash = hash_password(DEMO_PASSWORD)
    admin = User(
        email=ADMIN[0], full_name=ADMIN[1], hashed_password=hash_password(ADMIN[2]), role=UserRole.ADMIN
    )
    agents = [
        User(email=email, full_name=name, hashed_password=demo_hash, role=UserRole.AGENT)
        for email, name in AGENTS
    ]
    requesters = [
        User(email=email, full_name=name, hashed_password=demo_hash, role=UserRole.REQUESTER)
        for email, name in REQUESTERS
    ]
    db.add_all([admin, *agents, *requesters])

    for _ in range(ticket_count):
        # Skew ages towards recent days so the dashboard shows a realistic, busy recent period.
        age = timedelta(hours=days * 24 * rng.random() ** 1.3)
        db.add(_build_ticket(rng, now, rng.choice(requesters), agents, age))

    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepara la base de datos de HelpDesk Pro")
    parser.add_argument("--reset", action="store_true", help="borra todos los datos y vuelve a generarlos")
    args = parser.parse_args()

    if args.reset:
        reset_database()
    else:
        run_migrations()

    with SessionLocal() as db:
        if db.scalar(select(func.count(User.id))):
            print("La base de datos ya tiene datos: no se cargó nada. Usá --reset para regenerarla.")
            return
        seed_demo_data(db)
        tickets = db.scalar(select(func.count(Ticket.id)))

    print(f"Base de datos lista con {tickets} tickets de demo.")
    print(f"  Admin:       {ADMIN[0]} / {ADMIN[2]}")
    print(f"  Técnico:     {AGENTS[0][0]} / {DEMO_PASSWORD}")
    print(f"  Solicitante: {REQUESTERS[0][0]} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
