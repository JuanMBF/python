"""Support team dashboard: KPIs, trends and workload."""

import altair as alt
import pandas as pd
import streamlit as st

import ui
from api_client import ApiError

GRID_MUTED = "#c3c2b7"


def _kpis(stats: dict) -> None:
    sla = stats["sla_compliance_rate"]
    avg_hours = stats["avg_resolution_hours"]
    columns = st.columns(5)
    columns[0].metric(
        "Tickets activos",
        stats["active_tickets"],
        border=True,
        help="Abiertos, en progreso o en espera.",
    )
    columns[1].metric(
        "SLA vencido",
        stats["overdue_tickets"],
        border=True,
        help="Tickets activos que ya superaron su tiempo objetivo de resolución.",
    )
    columns[2].metric(
        "Sin asignar",
        stats["unassigned_tickets"],
        border=True,
        help="Tickets activos que todavía no tienen un técnico asignado.",
    )
    columns[3].metric(
        "Cumplimiento de SLA",
        f"{sla:.1f} %" if sla is not None else "—",
        border=True,
        help="Porcentaje de tickets resueltos dentro de su tiempo objetivo.",
    )
    columns[4].metric(
        "Resolución promedio",
        f"{avg_hours:.1f} h" if avg_hours is not None else "—",
        border=True,
        help="Promedio entre la creación y la resolución de cada ticket.",
    )


def _trend_chart(daily: list[dict]) -> alt.LayerChart:
    data = pd.DataFrame(daily).rename(columns={"created": "Creados", "resolved": "Resueltos"})
    data["day"] = pd.to_datetime(data["day"])
    long = data.melt("day", value_vars=["Creados", "Resueltos"], var_name="Serie", value_name="Tickets")

    encoding = {
        "x": alt.X("day:T", title=None, axis=alt.Axis(format="%d/%m", grid=False)),
        "y": alt.Y("Tickets:Q", title=None, axis=alt.Axis(tickMinStep=1)),
        "color": alt.Color(
            "Serie:N",
            scale=alt.Scale(domain=["Creados", "Resueltos"], range=[ui.SERIES_BLUE, ui.SERIES_ORANGE]),
            legend=alt.Legend(orient="top", title=None),
        ),
    }
    hover = alt.selection_point(
        nearest=True, on="pointerover", clear="pointerout", fields=["day"], empty=False
    )

    # Today is still in progress: its segment is dashed so the low count doesn't read as a real drop.
    today = long["day"].max()
    closed_days = long[long["day"] < today]
    current_day = long[long["day"] >= today - pd.Timedelta(days=1)]
    lines = alt.Chart(closed_days).mark_line(strokeWidth=2).encode(**encoding)
    partial = alt.Chart(current_day).mark_line(strokeWidth=2, strokeDash=[4, 4]).encode(**encoding)
    points = (
        alt.Chart(long)
        .mark_circle(size=70)
        .encode(**encoding, opacity=alt.condition(hover, alt.value(1), alt.value(0)))
    )
    crosshair = (
        alt.Chart(data)
        .mark_rule(color=GRID_MUTED, strokeWidth=1)
        .encode(
            x="day:T",
            opacity=alt.condition(hover, alt.value(1), alt.value(0)),
            tooltip=[
                alt.Tooltip("day:T", title="Día", format="%d/%m/%Y"),
                alt.Tooltip("Creados:Q"),
                alt.Tooltip("Resueltos:Q"),
            ],
        )
        .add_params(hover)
    )
    return alt.layer(lines, partial, points, crosshair).properties(height=320)


def _bar_chart(counts: dict[str, int], labels: dict, horizontal: bool, height: int) -> alt.LayerChart:
    data = pd.DataFrame({"key": list(counts), "Tickets": list(counts.values())})
    data["Nombre"] = data["key"].map(lambda key: labels[key][0])
    order = data["Nombre"].tolist()

    if horizontal:
        data = data.sort_values("Tickets", ascending=False)
        order = data["Nombre"].tolist()
        category_axis = alt.Y("Nombre:N", sort=order, title=None, axis=alt.Axis(ticks=False, domain=False))
        value_axis = alt.X("Tickets:Q", title=None, axis=None)
        bars = alt.Chart(data).mark_bar(cornerRadiusEnd=4, size=20, color=ui.SERIES_BLUE)
        text = alt.Chart(data).mark_text(align="left", dx=6)
    else:
        category_axis = alt.X("Nombre:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, ticks=False))
        value_axis = alt.Y("Tickets:Q", title=None, axis=alt.Axis(tickMinStep=1))
        bars = alt.Chart(data).mark_bar(cornerRadiusEnd=4, size=36, color=ui.SERIES_BLUE)
        text = alt.Chart(data).mark_text(baseline="bottom", dy=-4)

    encoding = {"x": value_axis, "y": category_axis} if horizontal else {"x": category_axis, "y": value_axis}
    tooltip = [alt.Tooltip("Nombre:N", title="Grupo"), alt.Tooltip("Tickets:Q")]
    return alt.layer(
        bars.encode(**encoding, tooltip=tooltip),
        text.encode(**encoding, text="Tickets:Q"),
    ).properties(height=height)


def _agents_table(agents: list[dict]) -> None:
    if not agents:
        st.info("Todavía no hay técnicos cargados.")
        return
    data = pd.DataFrame(agents).rename(
        columns={"agent_name": "Técnico", "active": "Activos", "overdue": "Vencidos", "resolved": "Resueltos"}
    )
    st.dataframe(
        data[["Técnico", "Activos", "Vencidos", "Resueltos"]],
        hide_index=True,
        width="stretch",
        column_config={
            "Activos": st.column_config.ProgressColumn(
                "Activos",
                help="Tickets activos asignados",
                format="%d",
                min_value=0,
                max_value=max(int(data["Activos"].max()), 1),
            ),
            "Vencidos": st.column_config.NumberColumn("Vencidos", help="Activos con SLA vencido"),
            "Resueltos": st.column_config.NumberColumn("Resueltos", help="Resueltos o cerrados (histórico)"),
        },
    )


def render() -> None:
    header, period = st.columns([3, 2], vertical_alignment="bottom")
    with header:
        st.title("Panel de control", anchor=False)
        st.caption("Estado de la mesa de ayuda en tiempo real.")
    with period:
        days = st.segmented_control(
            "Período",
            options=[7, 30, 90],
            default=30,
            required=True,
            format_func=lambda value: f"{value} días",
            label_visibility="collapsed",
        )

    try:
        stats = ui.client().stats(days=days)
    except ApiError as error:
        ui.handle_api_error(error)
        return

    _kpis(stats)

    trend, priority = st.columns([2, 1], gap="medium")
    with trend, st.container(border=True):
        st.markdown("#### Tickets creados vs. resueltos")
        st.altair_chart(_trend_chart(stats["daily"]), width="stretch")
    with priority, st.container(border=True):
        st.markdown("#### Activos por prioridad")
        st.altair_chart(
            _bar_chart(stats["active_by_priority"], ui.PRIORITY, horizontal=False, height=340),
            width="stretch",
        )

    category, agents = st.columns(2, gap="medium")
    with category, st.container(border=True):
        st.markdown("#### Tickets por categoría")
        st.altair_chart(
            _bar_chart(stats["by_category"], ui.CATEGORY, horizontal=True, height=260), width="stretch"
        )
    with agents, st.container(border=True):
        st.markdown("#### Carga de trabajo por técnico")
        _agents_table(stats["agents"])
