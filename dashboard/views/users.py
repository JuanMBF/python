"""User administration (admins only)."""

import pandas as pd
import streamlit as st

import ui
from api_client import ApiError


def _users_table(users: list[dict]) -> None:
    data = pd.DataFrame(
        [
            {
                "Nombre": user["full_name"],
                "Email": user["email"],
                "Rol": ui.ROLE[user["role"]],
                "Activo": user["is_active"],
                "Alta": ui.to_local(user["created_at"]).replace(tzinfo=None),
            }
            for user in users
        ]
    )
    st.dataframe(
        data,
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(data)),
        column_config={
            "Activo": st.column_config.CheckboxColumn(),
            "Alta": st.column_config.DateColumn(format="DD/MM/YYYY"),
        },
    )


def _create_user_form() -> None:
    with st.form("create_user", clear_on_submit=True, border=False):
        full_name = st.text_input("Nombre completo")
        email = st.text_input("Email", placeholder="nombre@empresa.com")
        role = st.selectbox("Rol", list(ui.ROLE), format_func=ui.ROLE.get)
        password = st.text_input("Contraseña inicial", type="password", help="Mínimo 8 caracteres.")
        submitted = st.form_submit_button("Crear usuario", type="primary", icon=":material/person_add:")
    if not submitted:
        return
    try:
        user = ui.client().create_user(full_name=full_name, email=email, role=role, password=password)
    except ApiError as error:
        ui.handle_api_error(error)
        return
    st.toast(f"Usuario {user['full_name']} creado.", icon=":material/check_circle:")
    st.rerun()


def _edit_user_form(users: list[dict]) -> None:
    by_id = {user["id"]: user for user in users}
    user_id = st.selectbox(
        "Usuario",
        list(by_id),
        format_func=lambda key: f"{by_id[key]['full_name']} ({by_id[key]['email']})",
    )
    user = by_id[user_id]
    with st.form(f"edit_user_{user_id}", border=False):
        role = st.selectbox(
            "Rol", list(ui.ROLE), index=list(ui.ROLE).index(user["role"]), format_func=ui.ROLE.get
        )
        is_active = st.toggle("Usuario activo", value=user["is_active"])
        password = st.text_input("Nueva contraseña", type="password", help="Dejar vacío para no cambiarla.")
        submitted = st.form_submit_button("Guardar", type="primary", icon=":material/save:")
    if not submitted:
        return

    changes: dict = {}
    if role != user["role"]:
        changes["role"] = role
    if is_active != user["is_active"]:
        changes["is_active"] = is_active
    if password:
        changes["password"] = password
    if not changes:
        st.toast("No hay cambios para guardar.", icon=":material/info:")
        return
    try:
        ui.client().update_user(user_id, **changes)
    except ApiError as error:
        ui.handle_api_error(error)
        return
    st.toast("Usuario actualizado.", icon=":material/check_circle:")
    st.rerun()


def render() -> None:
    st.title("Usuarios", anchor=False)
    st.caption("Alta de usuarios, cambio de roles y blanqueo de contraseñas.")

    try:
        users = ui.client().list_users()
    except ApiError as error:
        ui.handle_api_error(error)
        return

    plural = {"requester": "Solicitantes", "agent": "Técnicos", "admin": "Administradores"}
    columns = st.columns(len(plural))
    for column, (role, label) in zip(columns, plural.items(), strict=True):
        column.metric(label, sum(1 for user in users if user["role"] == role), border=True)

    _users_table(users)

    create, edit = st.columns(2, gap="large")
    with create, st.container(border=True):
        st.markdown("##### Nuevo usuario")
        _create_user_form()
    with edit, st.container(border=True):
        st.markdown("##### Editar usuario")
        _edit_user_form(users)
