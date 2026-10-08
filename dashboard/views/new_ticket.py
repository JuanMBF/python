"""Form to open a new support ticket."""

import streamlit as st

import ui
from api_client import ApiError

# Mirrors the API's SLA policy so the requester knows what to expect before submitting.
SLA_HOURS = {"critical": 4, "high": 8, "medium": 24, "low": 72}


def render() -> None:
    st.title("Nuevo ticket", anchor=False)
    st.caption("Contanos qué pasa y el equipo de soporte lo va a resolver lo antes posible.")

    form_column, tips_column = st.columns([2, 1], gap="large")
    with form_column, st.form("new_ticket", clear_on_submit=True):
        title = st.text_input(
            "Asunto", max_chars=200, placeholder="Ej.: La impresora del segundo piso no imprime"
        )
        category_column, priority_column = st.columns(2)
        category = category_column.selectbox(
            "Categoría", list(ui.CATEGORY), format_func=ui.category_label, index=None, placeholder="Elegí una"
        )
        priority = priority_column.selectbox(
            "Prioridad",
            list(ui.PRIORITY),
            index=1,
            format_func=lambda value: f"{ui.priority_label(value)} · resolución en {SLA_HOURS[value]} h",
        )
        description = st.text_area(
            "Descripción",
            height=180,
            max_chars=5000,
            placeholder="¿Qué estabas haciendo? ¿Qué mensaje de error aparece? ¿Desde cuándo pasa?",
        )
        submitted = st.form_submit_button("Crear ticket", type="primary", icon=":material/send:")

    with tips_column, st.container(border=True):
        st.markdown("##### Consejos para una resolución rápida")
        st.markdown(
            "- Indicá el **número de inventario** del equipo si lo tenés.\n"
            "- Copiá el **mensaje de error** exacto.\n"
            "- Contá qué **ya probaste** (reiniciar, otro cable, etc.).\n"
            "- Usá prioridad **crítica** solo si el problema frena a todo un área."
        )

    if not submitted:
        return
    errors = []
    if len(title.strip()) < 5:
        errors.append("El asunto debe tener al menos 5 caracteres.")
    if category is None:
        errors.append("Elegí una categoría.")
    if len(description.strip()) < 10:
        errors.append("La descripción debe tener al menos 10 caracteres.")
    if errors:
        for error in errors:
            st.warning(error, icon=":material/warning:")
        return

    try:
        ticket = ui.client().create_ticket(
            title=title.strip(), description=description.strip(), category=category, priority=priority
        )
    except ApiError as error:
        ui.handle_api_error(error)
        return
    st.success(
        f"Ticket **#{ticket['id']}** creado. Tiempo objetivo de resolución: "
        f"{ui.format_datetime(ticket['due_at'])}.",
        icon=":material/check_circle:",
    )
