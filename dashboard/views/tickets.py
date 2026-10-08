"""Ticket list with filters, plus the detail view (conversation, history and staff actions)."""

import pandas as pd
import streamlit as st

import ui
from api_client import ApiError, HelpDeskClient

PAGE_SIZE = 15
SORT_OPTIONS = {
    "-created_at": "Más recientes",
    "created_at": "Más antiguos",
    "-priority": "Mayor prioridad",
    "due_at": "Próximos a vencer",
    "-updated_at": "Última actividad",
}
UNASSIGNED = -1


@st.cache_data(ttl=60, show_spinner=False)
def _staff_members(token: str) -> list[dict]:
    return HelpDeskClient(token=token).list_users(roles=["agent", "admin"], is_active=True)


def _filters(staff: bool) -> dict:
    with st.container(border=True):
        search, status, priority, category = st.columns([1.6, 2.6, 1.4, 1.4])
        params: dict = {
            "q": search.text_input(
                "Buscar", placeholder="Título, descripción o #número", icon=":material/search:"
            ),
            "status": status.multiselect(
                "Estado",
                list(ui.STATUS),
                default=["open", "in_progress", "on_hold"],
                format_func=ui.status_label,
                placeholder="Todos",
            ),
            "priority": priority.multiselect(
                "Prioridad", list(ui.PRIORITY), format_func=ui.priority_label, placeholder="Todas"
            ),
            "category": category.multiselect(
                "Categoría", list(ui.CATEGORY), format_func=ui.category_label, placeholder="Todas"
            ),
        }
        toggles = st.container(horizontal=True, vertical_alignment="center", gap="medium")
        params["overdue"] = toggles.toggle("Solo SLA vencido")
        if staff:
            if toggles.toggle("Asignados a mí"):
                params["assignee_id"] = ui.current_user()["id"]
            params["unassigned"] = toggles.toggle("Sin asignar")
        params["sort"] = toggles.selectbox(
            "Orden",
            list(SORT_OPTIONS),
            format_func=SORT_OPTIONS.get,
            label_visibility="collapsed",
            width=200,
        )
    return params


def _highlight(column: str):
    """Cell styles for the ticket table: urgent priorities and SLA breaches stand out in red/orange."""

    def style(value: str) -> str:
        if column == "Prioridad":
            return {
                "Crítica": f"color: {ui.TEXT_DANGER}; font-weight: 600",
                "Alta": f"color: {ui.TEXT_WARNING}",
            }.get(value, "")
        return f"color: {ui.TEXT_DANGER}" if value.startswith("Vencido") or "fuera" in value else ""

    return style


def _table(items: list[dict], staff: bool, key: str) -> int | None:
    rows = [
        {
            "id": item["id"],
            "Ticket": f"#{item['id']}",
            "Asunto": item["title"],
            "Estado": ui.status_label(item["status"]),
            "Prioridad": ui.priority_label(item["priority"]),
            "Solicitante": item["requester"]["full_name"],
            "Técnico": item["assignee"]["full_name"] if item["assignee"] else "Sin asignar",
            "Creado": ui.time_ago(item["created_at"]),
            "SLA": ui.sla_text(item),
        }
        for item in items
    ]
    columns = ["Ticket", "Asunto", "Estado", "Prioridad", "Técnico", "Creado", "SLA"]
    if staff:
        columns.insert(4, "Solicitante")

    table = pd.DataFrame(rows)
    styled = table.style.map(_highlight("Prioridad"), subset=["Prioridad"]).map(
        _highlight("SLA"), subset=["SLA"]
    )
    event = st.dataframe(
        styled,
        column_order=columns,
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(rows)),
        on_select="rerun",
        selection_mode="single-row",
        key=key,
        column_config={"Ticket": st.column_config.TextColumn(width="small")},
    )
    selected = event.selection.rows
    return rows[selected[0]]["id"] if selected and selected[0] < len(rows) else None


def _staff_actions(ticket: dict) -> None:
    client = ui.client()
    staff = _staff_members(st.session_state["token"])
    assignee_options = [UNASSIGNED] + [member["id"] for member in staff]
    names = {member["id"]: member["full_name"] for member in staff} | {UNASSIGNED: "Sin asignar"}
    current_assignee = ticket["assignee"]["id"] if ticket["assignee"] else UNASSIGNED
    if current_assignee not in names:  # assigned to someone who is no longer active staff
        assignee_options.append(current_assignee)
        names[current_assignee] = ticket["assignee"]["full_name"]

    status_options = [ticket["status"], *ticket["allowed_statuses"]]
    disabled = ticket["status"] == "closed"

    with st.form(f"actions_{ticket['id']}", border=False):
        status = st.selectbox("Estado", status_options, format_func=ui.status_label, disabled=disabled)
        priority = st.selectbox(
            "Prioridad",
            list(ui.PRIORITY),
            index=list(ui.PRIORITY).index(ticket["priority"]),
            format_func=ui.priority_label,
            disabled=disabled,
        )
        category = st.selectbox(
            "Categoría",
            list(ui.CATEGORY),
            index=list(ui.CATEGORY).index(ticket["category"]),
            format_func=ui.category_label,
            disabled=disabled,
        )
        assignee = st.selectbox(
            "Técnico asignado",
            assignee_options,
            index=assignee_options.index(current_assignee),
            format_func=names.get,
            disabled=disabled,
        )
        submitted = st.form_submit_button(
            "Guardar cambios", type="primary", icon=":material/save:", width="stretch", disabled=disabled
        )

    if disabled:
        st.caption("Los tickets cerrados no se pueden modificar.")
    if not submitted:
        return

    changes: dict = {}
    if status != ticket["status"]:
        changes["status"] = status
    if priority != ticket["priority"]:
        changes["priority"] = priority
    if category != ticket["category"]:
        changes["category"] = category
    if assignee != current_assignee:
        changes["assignee_id"] = None if assignee == UNASSIGNED else assignee
    if not changes:
        st.toast("No hay cambios para guardar.", icon=":material/info:")
        return
    try:
        client.update_ticket(ticket["id"], **changes)
    except ApiError as error:
        ui.handle_api_error(error)
        return
    st.toast(f"Ticket #{ticket['id']} actualizado.", icon=":material/check_circle:")
    st.rerun()


def _conversation(ticket: dict, staff: bool) -> None:
    if not ticket["comments"]:
        st.caption("Todavía no hay mensajes en este ticket.")
    for comment in ticket["comments"]:
        author = comment["author"]
        avatar = ":material/support_agent:" if author["role"] != "requester" else ":material/person:"
        with st.chat_message(author["full_name"], avatar=avatar):
            meta = st.container(horizontal=True, vertical_alignment="center", gap="small")
            meta.markdown(f"**{author['full_name']}**")
            meta.caption(f"{ui.ROLE[author['role']]} · {ui.format_datetime(comment['created_at'])}")
            if comment["is_internal"]:
                meta.badge("Nota interna", icon=":material/lock:", color="orange")
            st.markdown(comment["body"])

    if ticket["status"] == "closed":
        return
    with st.form(f"comment_{ticket['id']}", clear_on_submit=True):
        body = st.text_area("Nuevo mensaje", placeholder="Escribí una respuesta…", height=100)
        internal = staff and st.checkbox("Nota interna (solo visible para técnicos)")
        sent = st.form_submit_button("Enviar", icon=":material/send:")
    if sent:
        if not body.strip():
            st.warning("El mensaje está vacío.")
            return
        try:
            ui.client().add_comment(ticket["id"], body.strip(), is_internal=internal)
        except ApiError as error:
            ui.handle_api_error(error)
            return
        st.rerun()


def _history(ticket: dict) -> None:
    for event in reversed(ticket["events"]):
        change = ""
        if event["event_type"] != "created":
            change = f": {ui.value_label(event['from_value'])} → **{ui.value_label(event['to_value'])}**"
        st.markdown(
            f"**{event['actor']['full_name']}** {ui.EVENT[event['event_type']]}{change}  \n"
            f":gray[{ui.format_datetime(event['created_at'])} · {ui.time_ago(event['created_at'])}]"
        )


def _detail(ticket_id: int, staff: bool) -> None:
    try:
        ticket = ui.client().get_ticket(ticket_id)
    except ApiError as error:
        ui.handle_api_error(error)
        return

    with st.container(border=True):
        title, close = st.columns([6, 1], vertical_alignment="center")
        title.subheader(f"#{ticket['id']} · {ticket['title']}", anchor=False)
        if close.button("Cerrar", icon=":material/close:", width="stretch"):
            st.session_state.pop("selected_ticket", None)
            # A new table key discards the row selection that opened this ticket.
            st.session_state["table_version"] = st.session_state.get("table_version", 0) + 1
            st.rerun()

        badges = st.container(horizontal=True, gap="small")
        with badges:
            ui.status_badge(ticket["status"])
            ui.priority_badge(ticket["priority"])
            ui.category_badge(ticket["category"])
            st.badge(
                ui.sla_text(ticket),
                icon=":material/timer:",
                color="red" if ticket["sla_breached"] else "green",
            )

        main, side = st.columns([2, 1], gap="large")
        with main:
            st.markdown("##### Descripción")
            st.markdown(ticket["description"])
            visible_comments = len(ticket["comments"])
            conversation, history = st.tabs(
                [f"Conversación ({visible_comments})", f"Historial ({len(ticket['events'])})"]
            )
            with conversation:
                _conversation(ticket, staff)
            with history:
                _history(ticket)
        with side:
            with st.container(border=True):
                st.markdown("##### Información")
                assignee = ticket["assignee"]["full_name"] if ticket["assignee"] else "Sin asignar"
                st.markdown(
                    f"**Solicitante:** {ticket['requester']['full_name']}  \n"
                    f"**Técnico:** {assignee}  \n"
                    f"**Creado:** {ui.format_datetime(ticket['created_at'])}  \n"
                    f"**Vencimiento SLA:** {ui.format_datetime(ticket['due_at'])}  \n"
                    f"**Resuelto:** {ui.format_datetime(ticket['resolved_at'])}"
                )
            if staff:
                with st.container(border=True):
                    st.markdown("##### Gestionar ticket")
                    _staff_actions(ticket)


def render() -> None:
    staff = ui.is_staff()
    st.title("Tickets" if staff else "Mis tickets", anchor=False)
    st.caption(
        "Seleccioná una fila para ver el detalle, responder o actualizar el ticket."
        if staff
        else "Seguí el estado de tus pedidos y conversá con el equipo de soporte."
    )

    params = _filters(staff)
    page = st.session_state.get("tickets_page", 1)
    try:
        result = ui.client().list_tickets(**params, page=page, size=PAGE_SIZE)
    except ApiError as error:
        ui.handle_api_error(error)
        return
    if result["pages"] and page > result["pages"]:  # filters changed and the page no longer exists
        st.session_state["tickets_page"] = 1
        st.rerun()

    if not result["items"]:
        st.info("No hay tickets que coincidan con los filtros.", icon=":material/inbox:")
    else:
        # The row selection must not survive a change in the listed tickets (e.g. one leaves the filter
        # after being resolved), otherwise the same row index would point to a different ticket.
        visible_ids = tuple(item["id"] for item in result["items"])
        table_key = f"tickets_{hash(visible_ids)}_{st.session_state.get('table_version', 0)}"
        selected = _table(result["items"], staff, key=table_key)
        if selected is not None:
            st.session_state["selected_ticket"] = selected

        info, pager = st.columns([3, 1], vertical_alignment="center")
        info.caption(f"{result['total']} tickets · página {result['page']} de {result['pages']}")
        with pager:
            buttons = st.container(horizontal=True, horizontal_alignment="right")
            if buttons.button("Anterior", icon=":material/chevron_left:", disabled=page <= 1):
                st.session_state["tickets_page"] = page - 1
                st.rerun()
            if buttons.button("Siguiente", icon=":material/chevron_right:", disabled=page >= result["pages"]):
                st.session_state["tickets_page"] = page + 1
                st.rerun()

    if "selected_ticket" in st.session_state:
        _detail(st.session_state["selected_ticket"], staff)
