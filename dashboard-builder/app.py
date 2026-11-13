"""Dashboard-Builder - einfache Tableau-Alternative mit Streamlit.

Start:  uv run streamlit run app.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import dashboard_core as core
from dashboard_core import COUNT_ROWS, ChartSpec

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "server" / "data"
NONE_LABEL = "(keins)"

st.set_page_config(page_title="Dashboard-Builder", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 3.5rem;}
.kpi-value {font-size: 2.6rem; font-weight: 700; color: #0f172a; line-height: 1.1;}
.kpi-sub {color: #64748b; font-size: 0.85rem;}
.field-dim {color: #2563eb;} .field-mea {color: #16a34a;}
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Session-State
# --------------------------------------------------------------------------- #

ss = st.session_state
ss.setdefault("charts", [])          # list[ChartSpec]
ss.setdefault("calculated", {})      # {name: ausdruck}
ss.setdefault("dash_name", "Mein Dashboard")
ss.setdefault("editing_id", None)
ss.setdefault("view", "Dashboard")
ss.setdefault("filter_cols", [])


@st.cache_data(show_spinner=False)
def load_sample(path: str) -> pd.DataFrame:
    return core.load_file(path, Path(path).read_bytes())


@st.cache_data(show_spinner=False)
def load_upload(name: str, data: bytes) -> pd.DataFrame:
    return core.load_file(name, data)


def fmt_opt(v):
    return NONE_LABEL if v is None else str(v)


# --------------------------------------------------------------------------- #
# Callbacks
# --------------------------------------------------------------------------- #

EDITOR_DEFAULTS = ChartSpec()


def set_editor(spec: ChartSpec) -> None:
    for key, value in spec.to_dict().items():
        ss[f"ed_{key}"] = value


def start_new_chart() -> None:
    ss.editing_id = None
    set_editor(ChartSpec())
    ss.view = "Diagramm-Editor"


def start_edit(chart_id: str) -> None:
    spec = next(c for c in ss.charts if c.id == chart_id)
    ss.editing_id = chart_id
    set_editor(spec)
    ss.view = "Diagramm-Editor"


def editor_spec() -> ChartSpec:
    fields = ChartSpec.__dataclass_fields__
    return ChartSpec(**{k: ss.get(f"ed_{k}", getattr(EDITOR_DEFAULTS, k)) for k in fields
                        if k != "id"})


def save_chart() -> None:
    spec = editor_spec()
    if ss.editing_id:
        spec.id = ss.editing_id
        ss.charts = [spec if c.id == ss.editing_id else c for c in ss.charts]
    else:
        ss.charts = [*ss.charts, spec]
    ss.editing_id = None
    ss.view = "Dashboard"


def cancel_edit() -> None:
    ss.editing_id = None
    ss.view = "Dashboard"


def delete_chart(chart_id: str) -> None:
    ss.charts = [c for c in ss.charts if c.id != chart_id]


def move_chart(chart_id: str, step: int) -> None:
    charts = list(ss.charts)
    i = next(i for i, c in enumerate(charts) if c.id == chart_id)
    j = max(0, min(len(charts) - 1, i + step))
    charts[i], charts[j] = charts[j], charts[i]
    ss.charts = charts


def toggle_width(chart_id: str) -> None:
    for c in ss.charts:
        if c.id == chart_id:
            c.width = "Halb" if c.width == "Voll" else "Voll"


def load_dashboard_file() -> None:
    upload = ss.get("dash_upload")
    if upload is None:
        return
    try:
        name, charts, filters, calculated = core.dashboard_from_json(upload.getvalue().decode())
    except Exception as exc:  # noqa: BLE001
        ss.load_error = f"Dashboard konnte nicht geladen werden: {exc}"
        return
    ss.dash_name, ss.charts, ss.calculated = name, charts, calculated
    ss.filter_cols = list(filters)
    for col, spec in filters.items():
        if "values" in spec:
            ss[f"flt_{col}"] = spec["values"]
        elif "range" in spec:
            lo, hi = spec["range"]
            if isinstance(lo, str):
                lo, hi = pd.Timestamp(lo).date(), pd.Timestamp(hi).date()
            ss[f"flt_{col}"] = (lo, hi)
    ss.view = "Dashboard"


def add_calculated() -> None:
    name, expr = ss.get("calc_name", "").strip(), ss.get("calc_expr", "").strip()
    if not name or not expr:
        ss.calc_error = "Name und Formel angeben."
        return
    try:
        core.add_calculated_field(ss["raw_df"].head(50), name, expr)
    except Exception as exc:  # noqa: BLE001
        ss.calc_error = f"Formel ungültig: {exc}"
        return
    ss.calculated = {**ss.calculated, name: expr}
    ss.calc_name, ss.calc_expr = "", ""


def remove_calculated(name: str) -> None:
    ss.calculated = {k: v for k, v in ss.calculated.items() if k != name}


def load_example_dashboard() -> None:
    """Startbeispiel für die Bestelldaten."""
    ss.dash_name = "Bestellungen - Übersicht"
    ss.calculated = {"Umsatz": "`items.quantity` * `items.unit_price`"}
    ss.charts = [
        ChartSpec(title="Umsatz gesamt", chart_type="KPI", y="Umsatz", agg="Summe"),
        ChartSpec(title="Anzahl Bestellungen", chart_type="KPI", y="order_number",
                  agg="Anzahl eindeutig"),
        ChartSpec(title="Umsatz pro Monat", chart_type="Linie", x="order_date", y="Umsatz",
                  agg="Summe", date_grain="Monat", width="Voll"),
        ChartSpec(title="Umsatz nach Lager und Status", chart_type="Balken", x="warehouse",
                  y="Umsatz", color="status"),
        ChartSpec(title="Anteil nach Kategorie", chart_type="Kreis", x="category",
                  y="Umsatz"),
        ChartSpec(title="Top 10 Kunden", chart_type="Balken horizontal", x="customer",
                  y="Umsatz", top_n=10, show_labels=True),
        ChartSpec(title="Bestellungen: Kategorie x Monat", chart_type="Heatmap",
                  x="order_date", color="category", date_grain="Monat"),
    ]


# --------------------------------------------------------------------------- #
# Sidebar: Daten, Felder, Filter, Speichern
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.header("Daten")
    samples = core.sample_datasets(SAMPLE_DIR)
    source = st.radio("Quelle", ["Beispieldaten", "Datei hochladen"], horizontal=True,
                      label_visibility="collapsed",
                      index=0 if samples else 1)
    raw_df, source_name = None, None
    if source == "Beispieldaten" and samples:
        names = list(samples)
        choice = st.selectbox("Datensatz", names,
                              index=names.index("orders") if "orders" in names else 0)
        raw_df, source_name = load_sample(str(samples[choice])), choice
    else:
        upload = st.file_uploader("CSV, Excel, JSON oder Parquet",
                                  type=["csv", "txt", "xlsx", "xls", "json", "parquet"])
        if upload is not None:
            try:
                raw_df = load_upload(upload.name, upload.getvalue())
                source_name = upload.name
            except Exception as exc:  # noqa: BLE001
                st.error(f"Datei konnte nicht gelesen werden: {exc}")

if raw_df is None:
    st.title("Dashboard-Builder")
    st.info("Links eine Datenquelle wählen oder eine Datei hochladen, um zu starten.")
    st.stop()

ss["raw_df"] = raw_df

# Berechnete Felder anwenden
df = raw_df
calc_errors = []
for name, expr in ss.calculated.items():
    try:
        df = core.add_calculated_field(df, name, expr)
    except Exception as exc:  # noqa: BLE001
        calc_errors.append(f"{name}: {exc}")

dims, meas, dates = core.dimensions(df), core.measures(df), core.date_columns(df)

with st.sidebar:
    st.caption(f"{source_name}: {len(df):,} Zeilen, {len(df.columns)} Spalten".replace(",", "."))

    with st.expander("Felder", expanded=False):
        st.markdown("**Dimensionen**")
        st.markdown("\n".join(f"- <span class='field-dim'>{c}</span>"
                              f"{' (Datum)' if c in dates else ''}" for c in dims),
                    unsafe_allow_html=True)
        st.markdown("**Kennzahlen**")
        st.markdown("\n".join(f"- <span class='field-mea'>{c}</span>" for c in meas),
                    unsafe_allow_html=True)

    with st.expander("Berechnete Felder", expanded=bool(ss.calculated)):
        for name, expr in ss.calculated.items():
            st.markdown(f"**{name}** = `{expr}`")
            st.button("Entfernen", key=f"rmcalc_{name}", on_click=remove_calculated,
                      args=(name,), type="tertiary")
        st.text_input("Name", key="calc_name", placeholder="z. B. Umsatz")
        st.text_input("Formel", key="calc_expr",
                      placeholder="`items.quantity` * `items.unit_price`",
                      help="Rechnen mit Spalten: + - * / ( ). Spaltennamen mit Punkt oder "
                           "Leerzeichen in Backticks setzen.")
        st.button("Feld hinzufügen", on_click=add_calculated, use_container_width=True)
        if err := ss.pop("calc_error", None):
            st.error(err)
        for err in calc_errors:
            st.error(err)

    st.header("Filter")
    ss.filter_cols = [c for c in ss.filter_cols if c in df.columns]
    filter_cols = st.multiselect("Felder filtern", list(df.columns), key="filter_cols",
                                 placeholder="Feld wählen")
    filters: dict = {}
    for col in filter_cols:
        series = df[col]
        key = f"flt_{col}"
        if pd.api.types.is_datetime64_any_dtype(series):
            lo, hi = series.min().date(), series.max().date()
            ss.setdefault(key, (lo, hi))
            value = st.date_input(col, min_value=lo, max_value=hi, key=key)
            if isinstance(value, (tuple, list)) and len(value) == 2:
                filters[col] = {"range": [value[0], value[1]]}
        elif col in meas:
            lo, hi = float(series.min()), float(series.max())
            if lo < hi:
                ss.setdefault(key, (lo, hi))
                value = st.slider(col, lo, hi, key=key)
                filters[col] = {"range": list(value)}
        else:
            options = sorted(series.dropna().astype(str).unique())[:1000]
            ss[key] = [v for v in ss.get(key, []) if v in options]
            value = st.multiselect(col, options, key=key, placeholder="Alle")
            if value:
                filters[col] = {"values": value}

    st.header("Dashboard")
    st.download_button(
        "Dashboard speichern (.json)",
        core.dashboard_to_json(ss.dash_name, ss.charts, filters, ss.calculated),
        file_name=f"{ss.dash_name}.json", mime="application/json", use_container_width=True)
    st.file_uploader("Dashboard laden", type=["json"], key="dash_upload",
                     on_change=load_dashboard_file)
    if err := ss.pop("load_error", None):
        st.error(err)

fdf = core.apply_filters(df, filters)


# --------------------------------------------------------------------------- #
# Hauptbereich
# --------------------------------------------------------------------------- #

head_l, head_r = st.columns([3, 2], vertical_alignment="bottom")
head_l.text_input("Dashboard-Name", key="dash_name", label_visibility="collapsed")
with head_r:
    b1, b2 = st.columns(2)
    b1.button("+ Neues Diagramm", on_click=start_new_chart, type="primary",
              use_container_width=True)
    b2.download_button("Als HTML exportieren",
                       core.export_html(ss.dash_name, fdf, ss.charts),
                       file_name=f"{ss.dash_name}.html", mime="text/html",
                       use_container_width=True, disabled=not ss.charts)

if filters:
    st.caption(f"Gefiltert: {len(fdf):,} von {len(df):,} Zeilen".replace(",", "."))

view = st.segmented_control("Ansicht", ["Dashboard", "Diagramm-Editor", "Daten"],
                            key="view", label_visibility="collapsed")


def render_chart_body(spec: ChartSpec, data: pd.DataFrame, key: str) -> None:
    try:
        if spec.chart_type == "KPI":
            value = core.kpi_value(data, spec)
            label = "Anzahl Zeilen" if spec.y in (None, COUNT_ROWS) else f"{spec.agg} von {spec.y}"
            st.markdown(f"<div class='kpi-value'>{core.format_number(value)}</div>"
                        f"<div class='kpi-sub'>{label}</div>", unsafe_allow_html=True)
        elif spec.chart_type == "Tabelle":
            st.dataframe(core.pivot_table(data, spec), use_container_width=True, height=360)
        else:
            fig = core.build_figure(data, spec)
            st.plotly_chart(fig, use_container_width=True, key=key, theme=None)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Diagramm kann nicht angezeigt werden: {exc}")


# ---------------- Dashboard ----------------
if view in (None, "Dashboard"):
    if not ss.charts:
        st.info("Noch keine Diagramme. Mit **+ Neues Diagramm** anfangen.")
        if source_name == "orders":
            st.button("Beispiel-Dashboard für Bestellungen laden",
                      on_click=load_example_dashboard)

    # KPIs als Reihe oben, Rest im 2-Spalten-Raster
    kpis = [c for c in ss.charts if c.chart_type == "KPI"]
    others = [c for c in ss.charts if c.chart_type != "KPI"]

    def chart_toolbar(spec: ChartSpec) -> None:
        t, menu = st.columns([5, 1], vertical_alignment="center")
        t.markdown(f"**{spec.title}**")
        with menu.popover("...", use_container_width=True):
            st.button("Bearbeiten", key=f"edit_{spec.id}", on_click=start_edit,
                      args=(spec.id,), use_container_width=True)
            st.button("Nach vorne", key=f"up_{spec.id}", on_click=move_chart,
                      args=(spec.id, -1), use_container_width=True)
            st.button("Nach hinten", key=f"dn_{spec.id}", on_click=move_chart,
                      args=(spec.id, 1), use_container_width=True)
            if spec.chart_type != "KPI":
                st.button("Breite halb / voll", key=f"w_{spec.id}", on_click=toggle_width,
                          args=(spec.id,), use_container_width=True)
            st.button("Löschen", key=f"del_{spec.id}", on_click=delete_chart,
                      args=(spec.id,), use_container_width=True)

    if kpis:
        for col, spec in zip(st.columns(len(kpis)), kpis):
            with col, st.container(border=True):
                chart_toolbar(spec)
                render_chart_body(spec, fdf, f"plot_{spec.id}")

    row: list[ChartSpec] = []

    def flush(items: list[ChartSpec]) -> None:
        if not items:
            return
        cols = st.columns(2) if len(items) == 2 else [st.container()]
        for col, spec in zip(cols, items):
            with col, st.container(border=True):
                chart_toolbar(spec)
                render_chart_body(spec, fdf, f"plot_{spec.id}")

    for spec in others:
        if spec.width == "Voll":
            flush(row)
            row = []
            flush([spec])
        else:
            row.append(spec)
            if len(row) == 2:
                flush(row)
                row = []
    if row:
        cols = st.columns(2)
        with cols[0], st.container(border=True):
            chart_toolbar(row[0])
            render_chart_body(row[0], fdf, f"plot_{row[0].id}")


# ---------------- Editor ----------------
elif view == "Diagramm-Editor":
    if "ed_title" not in ss:
        set_editor(ChartSpec())
    all_cols = list(df.columns)
    # ungültige Feldwerte (z. B. nach Datenwechsel) zurücksetzen
    for k in ("ed_x", "ed_color"):
        if ss.get(k) not in [None, *all_cols]:
            ss[k] = None
    if ss.get("ed_y") not in [COUNT_ROWS, *all_cols]:
        ss.ed_y = COUNT_ROWS

    left, right = st.columns([1, 2], gap="large")
    with left:
        st.subheader("Bearbeiten" if ss.editing_id else "Neues Diagramm")
        st.text_input("Titel", key="ed_title")
        st.selectbox("Diagrammtyp", core.CHART_TYPES, key="ed_chart_type")
        ctype = ss.ed_chart_type

        if ctype != "KPI":
            x_label = "Feld" if ctype == "Histogramm" else "Spalten / X-Achse (Dimension)"
            st.selectbox(x_label, [None, *dims, *meas], key="ed_x", format_func=fmt_opt,
                         placeholder=NONE_LABEL)
        y_label = "Y-Feld" if ctype in core.NO_AGG_TYPES else "Wert (Kennzahl)"
        st.selectbox(y_label, [COUNT_ROWS, *meas, *dims], key="ed_y")
        if ctype not in core.NO_AGG_TYPES:
            st.selectbox("Aggregation", list(core.AGGREGATIONS), key="ed_agg",
                         disabled=ss.ed_y == COUNT_ROWS)
        if ctype not in ("KPI",):
            color_label = "Zeilen (Y)" if ctype == "Heatmap" else "Farbe / Aufteilen nach"
            st.selectbox(color_label, [None, *dims], key="ed_color", format_func=fmt_opt,
                         placeholder=NONE_LABEL)

        uses_date = any(ss.get(k) in dates for k in ("ed_x", "ed_color"))
        if uses_date and ctype not in core.NO_AGG_TYPES:
            st.selectbox("Datum gruppieren nach", list(core.DATE_GRAINS), key="ed_date_grain")

        if ctype not in ("KPI", "Streuung", "Histogramm"):
            st.selectbox("Sortierung", ["Wert absteigend", "Wert aufsteigend",
                                         "Achse aufsteigend"], key="ed_sort")
            st.number_input("Nur Top N anzeigen (0 = alle)", 0, 1000, step=1, key="ed_top_n")
        if ctype in ("Balken", "Balken horizontal", "Linie", "Heatmap"):
            st.checkbox("Werte beschriften", key="ed_show_labels")
        st.radio("Breite im Dashboard", ["Halb", "Voll"], key="ed_width", horizontal=True)

        c1, c2 = st.columns(2)
        c1.button("Speichern" if ss.editing_id else "Hinzufügen",
                  type="primary", on_click=save_chart, use_container_width=True)
        c2.button("Abbrechen", on_click=cancel_edit, use_container_width=True)

    with right:
        spec = editor_spec()
        st.subheader(spec.title or "Vorschau")
        with st.container(border=True):
            render_chart_body(spec, fdf, "preview")
        if spec.chart_type not in ("KPI", "Streuung", "Histogramm", "Tabelle"):
            with st.expander("Aggregierte Daten ansehen"):
                try:
                    st.dataframe(core.aggregate(fdf, spec), use_container_width=True)
                except Exception as exc:  # noqa: BLE001
                    st.caption(str(exc))


# ---------------- Daten ----------------
elif view == "Daten":
    st.dataframe(fdf, use_container_width=True, height=480)
    with st.expander("Statistik"):
        if meas:
            st.dataframe(fdf[meas].describe().T, use_container_width=True)
        st.write({c: str(t) for c, t in df.dtypes.items()})
    st.download_button("Gefilterte Daten als CSV", fdf.to_csv(index=False).encode("utf-8"),
                       file_name=f"{source_name}_gefiltert.csv", mime="text/csv")
