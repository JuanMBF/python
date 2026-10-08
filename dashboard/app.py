"""HelpDesk Pro web dashboard: ``streamlit run dashboard/app.py``."""

import os

import streamlit as st

import ui
from api_client import ApiError, HelpDeskClient
from views import new_ticket, panel, tickets, users

DEMO_MODE = os.getenv("HELPDESK_DEMO_MODE", "true").lower() == "true"
DEMO_ACCOUNTS = {
    "Administrador": ("admin@example.com", "Admin1234!", ":material/admin_panel_settings:"),
    "Técnico": ("lucia.fernandez@example.com", "Demo1234!", ":material/support_agent:"),
    "Solicitante": ("valentina.lopez@example.com", "Demo1234!", ":material/person:"),
}

st.set_page_config(page_title="HelpDesk Pro", page_icon=":material/support_agent:", layout="wide")


def _login(email: str, password: str) -> None:
    client = HelpDeskClient()
    try:
        st.session_state["token"] = client.login(email.strip(), password)
        st.session_state["user"] = client.me()
    except ApiError as error:
        st.session_state.pop("token", None)
        st.error(error.message, icon=":material/error:")
        return
    st.rerun()


def login_page() -> None:
    _, center, _ = st.columns([1, 1.3, 1])
    with center:
        st.space("large")
        st.title(":material/support_agent: HelpDesk Pro", anchor=False)
        st.caption("Sistema de gestión de tickets de soporte IT")

        with st.form("login"):
            email = st.text_input("Email", placeholder="usuario@empresa.com")
            password = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button(
                "Ingresar", type="primary", icon=":material/login:", width="stretch"
            )
        if submitted:
            _login(email, password)

        if DEMO_MODE:
            st.caption("¿Querés probarlo? Entrá con un usuario de demo:")
            demo = st.container(horizontal=True, gap="small")
            for label, (demo_email, demo_password, icon) in DEMO_ACCOUNTS.items():
                if demo.button(label, icon=icon, width="stretch"):
                    _login(demo_email, demo_password)


def sidebar(user: dict) -> None:
    with st.sidebar, st.container(border=True):
        st.markdown(f"**{user['full_name']}**")
        st.badge(ui.ROLE[user["role"]], icon=":material/badge:", color="blue")
        st.text(user["email"])
        if st.button("Cerrar sesión", icon=":material/logout:", width="stretch"):
            st.session_state.clear()
            st.cache_data.clear()
            st.rerun()


def main() -> None:
    if "token" not in st.session_state:
        login_page()
        return

    user = ui.current_user()
    sidebar(user)

    if ui.is_staff():
        pages = {
            "Mesa de ayuda": [
                st.Page(
                    panel.render, title="Panel", icon=":material/dashboard:", url_path="panel", default=True
                ),
                st.Page(
                    tickets.render, title="Tickets", icon=":material/confirmation_number:", url_path="tickets"
                ),
                st.Page(
                    new_ticket.render, title="Nuevo ticket", icon=":material/add_circle:", url_path="nuevo"
                ),
            ]
        }
        if user["role"] == "admin":
            pages["Administración"] = [
                st.Page(users.render, title="Usuarios", icon=":material/group:", url_path="usuarios")
            ]
    else:
        pages = {
            "Soporte IT": [
                st.Page(
                    tickets.render,
                    title="Mis tickets",
                    icon=":material/confirmation_number:",
                    url_path="tickets",
                    default=True,
                ),
                st.Page(
                    new_ticket.render, title="Nuevo ticket", icon=":material/add_circle:", url_path="nuevo"
                ),
            ]
        }

    st.navigation(pages).run()


main()
