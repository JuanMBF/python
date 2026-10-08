"""Labels, colors and formatting helpers shared by every dashboard page."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from api_client import ApiError, HelpDeskClient

TIMEZONE = ZoneInfo(os.getenv("HELPDESK_TIMEZONE", "America/Argentina/Buenos_Aires"))

# Chart colors (validated, colorblind-safe categorical slots).
SERIES_BLUE = "#2a78d6"
SERIES_ORANGE = "#eb6834"
# Text colors for table cells (meet 4.5:1 contrast on the light background).
TEXT_DANGER = "#b42318"
TEXT_WARNING = "#b54708"

STATUS = {
    "open": ("Abierto", "blue", ":material/fiber_new:"),
    "in_progress": ("En progreso", "orange", ":material/autorenew:"),
    "on_hold": ("En espera", "violet", ":material/pause_circle:"),
    "resolved": ("Resuelto", "green", ":material/check_circle:"),
    "closed": ("Cerrado", "gray", ":material/lock:"),
}
PRIORITY = {
    "low": ("Baja", "gray", ":material/keyboard_double_arrow_down:"),
    "medium": ("Media", "blue", ":material/drag_handle:"),
    "high": ("Alta", "orange", ":material/keyboard_arrow_up:"),
    "critical": ("Crítica", "red", ":material/priority_high:"),
}
CATEGORY = {
    "hardware": ("Hardware", ":material/computer:"),
    "software": ("Software", ":material/apps:"),
    "network": ("Redes", ":material/wifi:"),
    "access": ("Accesos y cuentas", ":material/key:"),
    "email": ("Correo", ":material/mail:"),
    "other": ("Otros", ":material/help:"),
}
ROLE = {"requester": "Solicitante", "agent": "Técnico", "admin": "Administrador"}
EVENT = {
    "created": "creó el ticket",
    "status_changed": "cambió el estado",
    "priority_changed": "cambió la prioridad",
    "category_changed": "cambió la categoría",
    "assigned": "cambió el técnico asignado",
}


def status_label(value: str) -> str:
    return STATUS[value][0]


def priority_label(value: str) -> str:
    return PRIORITY[value][0]


def category_label(value: str) -> str:
    return CATEGORY[value][0]


def value_label(value: str | None) -> str:
    """Human label for any enum value stored in the ticket history."""
    if value is None:
        return "—"
    for mapping in (STATUS, PRIORITY, CATEGORY):
        if value in mapping:
            return mapping[value][0]
    return value


def status_badge(value: str) -> None:
    label, color, icon = STATUS[value]
    st.badge(label, color=color, icon=icon)


def priority_badge(value: str) -> None:
    label, color, icon = PRIORITY[value]
    st.badge(f"Prioridad {label.lower()}", color=color, icon=icon)


def category_badge(value: str) -> None:
    label, icon = CATEGORY[value]
    st.badge(label, color="gray", icon=icon)


# --- dates ------------------------------------------------------------------------------------


def to_local(value: str | datetime) -> datetime:
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    return moment.astimezone(TIMEZONE)


def format_datetime(value: str | None) -> str:
    return to_local(value).strftime("%d/%m/%Y %H:%M") if value else "—"


def _humanize(seconds: float) -> str:
    minutes = int(abs(seconds) // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h"
    return f"{hours // 24} días"


def time_ago(value: str) -> str:
    seconds = (datetime.now(TIMEZONE) - to_local(value)).total_seconds()
    return "recién" if seconds < 60 else f"hace {_humanize(seconds)}"


def sla_text(ticket: dict) -> str:
    if ticket["resolved_at"]:
        return "Resuelto fuera de SLA" if ticket["sla_breached"] else "Resuelto dentro del SLA"
    remaining = (to_local(ticket["due_at"]) - datetime.now(TIMEZONE)).total_seconds()
    if remaining < 0:
        return f"Vencido hace {_humanize(remaining)}"
    return f"Vence en {_humanize(remaining)}"


def table_height(rows: int, max_rows: int = 15) -> int:
    """Pixel height that shows every row of a dataframe (up to ``max_rows``) without inner scrolling."""
    return (min(rows, max_rows) + 1) * 35 + 3


# --- session ----------------------------------------------------------------------------------


def client() -> HelpDeskClient:
    return HelpDeskClient(token=st.session_state.get("token"))


def current_user() -> dict:
    return st.session_state["user"]


def is_staff() -> bool:
    return current_user()["role"] in ("agent", "admin")


def handle_api_error(error: ApiError) -> None:
    """Show an API error; if the session expired, log the user out."""
    if error.status_code == 401:
        st.session_state.clear()
        st.warning("Tu sesión expiró. Volvé a iniciar sesión.", icon=":material/lock_clock:")
        st.rerun()
    st.error(error.message, icon=":material/error:")
