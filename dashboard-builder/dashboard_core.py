"""Kernlogik des Dashboard-Builders: Daten laden, aggregieren, Diagramme bauen.

Bewusst ohne Streamlit-Abhängigkeit, damit alles testbar und wiederverwendbar ist.
"""

from __future__ import annotations

import io
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

AGGREGATIONS = {
    "Summe": "sum",
    "Mittelwert": "mean",
    "Median": "median",
    "Anzahl": "count",
    "Anzahl eindeutig": "nunique",
    "Minimum": "min",
    "Maximum": "max",
}

DATE_GRAINS = {
    "Exakt": None,
    "Tag": "D",
    "Woche": "W",
    "Monat": "M",
    "Quartal": "Q",
    "Jahr": "Y",
}

CHART_TYPES = [
    "Balken",
    "Balken horizontal",
    "Linie",
    "Fläche",
    "Kreis",
    "Streuung",
    "Histogramm",
    "Heatmap",
    "Treemap",
    "KPI",
    "Tabelle",
]

# Diagrammtypen, die keine Kennzahl-Aggregation brauchen
NO_AGG_TYPES = {"Streuung", "Histogramm"}

PALETTE = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed",
           "#0891b2", "#db2777", "#65a30d", "#ea580c", "#475569"]

COUNT_ROWS = "(Anzahl Zeilen)"


# --------------------------------------------------------------------------- #
# Daten laden
# --------------------------------------------------------------------------- #

def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Textspalten, die wie Datumswerte aussehen, in datetime umwandeln."""
    for col in df.columns:
        if not (df[col].dtype == object or pd.api.types.is_string_dtype(df[col])):
            continue
        sample = df[col].dropna().astype(str).head(50)
        if sample.empty or not sample.str.match(r"^\d{4}-\d{2}-\d{2}").all():
            continue
        parsed = pd.to_datetime(df[col], errors="coerce")
        if parsed.notna().mean() > 0.9:
            df[col] = parsed
    return df


def records_to_frame(records: list | dict) -> pd.DataFrame:
    """JSON-Datensätze in eine flache Tabelle umwandeln.

    Listen mit Unterobjekten (z. B. Bestellpositionen) werden zu eigenen Zeilen
    expandiert, damit man sie wie in Tableau direkt auswerten kann.
    """
    if isinstance(records, dict):
        # {"key": [...]} -> erste Liste nehmen, sonst einzelner Datensatz
        lists = [v for v in records.values() if isinstance(v, list)]
        records = lists[0] if lists else [records]

    df = pd.json_normalize(records)
    for col in list(df.columns):
        non_null = df[col].dropna()
        if non_null.empty:
            continue
        if non_null.map(lambda v: isinstance(v, list) and v and isinstance(v[0], dict)).all():
            df = df.explode(col, ignore_index=True)
            nested = pd.json_normalize(df[col].tolist()).add_prefix(f"{col}.")
            df = pd.concat([df.drop(columns=[col]), nested], axis=1)
        elif non_null.map(lambda v: isinstance(v, list)).any():
            df[col] = df[col].map(lambda v: ", ".join(map(str, v)) if isinstance(v, list) else v)
    return _parse_dates(df)


def load_file(name: str, data: bytes) -> pd.DataFrame:
    """Hochgeladene Datei (CSV, Excel, JSON, Parquet) einlesen."""
    suffix = Path(name).suffix.lower()
    buf = io.BytesIO(data)
    if suffix in {".csv", ".txt"}:
        text = data.decode("utf-8-sig", errors="replace")
        sep = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
        decimal = "," if sep == ";" else "."
        df = pd.read_csv(io.StringIO(text), sep=sep, decimal=decimal)
        return _parse_dates(df)
    if suffix in {".xlsx", ".xls"}:
        return _parse_dates(pd.read_excel(buf))
    if suffix == ".json":
        return records_to_frame(json.loads(data.decode("utf-8")))
    if suffix == ".parquet":
        return pd.read_parquet(buf)
    raise ValueError(f"Dateityp {suffix} wird nicht unterstützt")


def sample_datasets(data_dir: Path) -> dict[str, Path]:
    if not data_dir.is_dir():
        return {}
    return {p.stem: p for p in sorted(data_dir.glob("*.json"))}


# --------------------------------------------------------------------------- #
# Felder klassifizieren (Dimensionen vs. Kennzahlen)
# --------------------------------------------------------------------------- #

def dimensions(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])
            or pd.api.types.is_bool_dtype(df[c])]


def measures(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
            and not pd.api.types.is_bool_dtype(df[c])]


def date_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]


def add_calculated_field(df: pd.DataFrame, name: str, expression: str) -> pd.DataFrame:
    """Berechnetes Feld, z. B. `quantity * unit_price`.

    Spaltennamen mit Punkten/Leerzeichen in Backticks schreiben: `items.quantity`.
    """
    out = df.copy()
    out[name] = out.eval(expression, engine="python")
    return out


# --------------------------------------------------------------------------- #
# Filter
# --------------------------------------------------------------------------- #

def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """filters: {spalte: {"values": [...]} | {"range": [lo, hi]}}"""
    mask = pd.Series(True, index=df.index)
    for col, spec in filters.items():
        if col not in df.columns:
            continue
        if "values" in spec and spec["values"]:
            mask &= df[col].astype(str).isin([str(v) for v in spec["values"]])
        elif "range" in spec and spec["range"]:
            lo, hi = spec["range"]
            series = df[col]
            if pd.api.types.is_datetime64_any_dtype(series):
                lo, hi = pd.Timestamp(lo), pd.Timestamp(hi) + pd.Timedelta(days=1)
                mask &= (series >= lo) & (series < hi)
            else:
                mask &= series.between(lo, hi)
    return df[mask]


# --------------------------------------------------------------------------- #
# Diagramm-Definition
# --------------------------------------------------------------------------- #

@dataclass
class ChartSpec:
    title: str = "Neues Diagramm"
    chart_type: str = "Balken"
    x: str | None = None
    y: str | None = COUNT_ROWS
    agg: str = "Summe"
    color: str | None = None
    date_grain: str = "Monat"
    sort: str = "Wert absteigend"
    top_n: int = 0
    width: str = "Halb"
    show_labels: bool = False
    id: str = field(default_factory=lambda: pd.Timestamp.now().strftime("%H%M%S%f"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ChartSpec":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _value_label(spec: ChartSpec) -> str:
    if spec.y in (None, COUNT_ROWS):
        return "Anzahl"
    return f"{spec.agg}({spec.y})"


def aggregate(df: pd.DataFrame, spec: ChartSpec) -> pd.DataFrame:
    """Daten für ein Diagramm gruppieren und aggregieren."""
    work = df.copy()
    value = _value_label(spec)
    group_cols: list[str] = []

    for col in (spec.x, spec.color):
        if col and col not in group_cols:
            group_cols.append(col)
            grain = DATE_GRAINS.get(spec.date_grain)
            if grain and pd.api.types.is_datetime64_any_dtype(work[col]):
                work[col] = work[col].dt.to_period(grain).dt.start_time

    if spec.y in (None, COUNT_ROWS):
        if group_cols:
            result = work.groupby(group_cols, dropna=False).size().reset_index(name=value)
        else:
            result = pd.DataFrame({value: [len(work)]})
    else:
        func = AGGREGATIONS[spec.agg]
        if group_cols:
            result = (work.groupby(group_cols, dropna=False)[spec.y]
                      .agg(func).reset_index(name=value))
        else:
            result = pd.DataFrame({value: [work[spec.y].agg(func)]})

    if spec.x and spec.x in result.columns:
        is_time = pd.api.types.is_datetime64_any_dtype(result[spec.x])
        if is_time or spec.sort == "Achse aufsteigend":
            result = result.sort_values(spec.x)
        elif spec.sort == "Wert absteigend":
            order = result.groupby(spec.x)[value].sum().sort_values(ascending=False).index
            result = result.set_index(spec.x).loc[order].reset_index()
        elif spec.sort == "Wert aufsteigend":
            order = result.groupby(spec.x)[value].sum().sort_values().index
            result = result.set_index(spec.x).loc[order].reset_index()

        if spec.top_n and not is_time:
            keep = list(dict.fromkeys(result[spec.x]))[: spec.top_n]
            result = result[result[spec.x].isin(keep)]
    return result


def format_number(value: float) -> str:
    if pd.isna(value):
        return "-"
    abs_v = abs(value)
    for limit, suffix in ((1e9, " Mrd"), (1e6, " Mio"), (1e3, " Tsd")):
        if abs_v >= limit:
            return f"{value / limit:,.1f}{suffix}".replace(",", "X").replace(".", ",").replace("X", ".")
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", ".")
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_figure(df: pd.DataFrame, spec: ChartSpec) -> go.Figure | None:
    """Plotly-Figur für eine Diagramm-Definition. KPI/Tabelle -> None."""
    if spec.chart_type in ("KPI", "Tabelle"):
        return None

    common = dict(color_discrete_sequence=PALETTE, template="plotly_white")

    if spec.chart_type == "Streuung":
        y = spec.y if spec.y not in (None, COUNT_ROWS) else None
        if not spec.x or not y:
            raise ValueError("Streuung braucht X und Y als Felder")
        fig = px.scatter(df, x=spec.x, y=y, color=spec.color, **common)
    elif spec.chart_type == "Histogramm":
        col = spec.y if spec.y not in (None, COUNT_ROWS) else spec.x
        if not col:
            raise ValueError("Histogramm braucht ein Feld")
        fig = px.histogram(df, x=col, color=spec.color, **common)
    else:
        if not spec.x:
            raise ValueError("Bitte ein Feld für die X-Achse wählen")
        data = aggregate(df, spec)
        value = _value_label(spec)
        text = value if spec.show_labels else None
        if spec.chart_type == "Balken":
            fig = px.bar(data, x=spec.x, y=value, color=spec.color, text=text, **common)
        elif spec.chart_type == "Balken horizontal":
            fig = px.bar(data, y=spec.x, x=value, color=spec.color, text=text,
                         orientation="h", **common)
            fig.update_yaxes(autorange="reversed")
        elif spec.chart_type == "Linie":
            fig = px.line(data, x=spec.x, y=value, color=spec.color, markers=True,
                          text=text, **common)
        elif spec.chart_type == "Fläche":
            fig = px.area(data, x=spec.x, y=value, color=spec.color, **common)
        elif spec.chart_type == "Kreis":
            fig = px.pie(data, names=spec.x, values=value, hole=0.45, **common)
        elif spec.chart_type == "Heatmap":
            if not spec.x or not spec.color:
                raise ValueError("Heatmap braucht X und 'Farbe / Aufteilen nach'")
            pivot = data.pivot_table(index=spec.color, columns=spec.x, values=value,
                                     aggfunc="sum")
            fig = px.imshow(pivot, aspect="auto", color_continuous_scale="Blues",
                            text_auto=spec.show_labels, template="plotly_white")
        elif spec.chart_type == "Treemap":
            path = [c for c in (spec.color, spec.x) if c]
            if not path:
                raise ValueError("Treemap braucht X")
            fig = px.treemap(data, path=path, values=value, **common)
        else:
            raise ValueError(f"Unbekannter Diagrammtyp: {spec.chart_type}")

    fig.update_layout(
        title=None,
        margin=dict(l=10, r=10, t=10, b=10),
        height=360,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(color="#0f172a"),
    )
    return fig


def kpi_value(df: pd.DataFrame, spec: ChartSpec) -> float:
    kpi = ChartSpec(**{**spec.to_dict(), "x": None, "color": None})
    return float(aggregate(df, kpi).iloc[0, -1])


def pivot_table(df: pd.DataFrame, spec: ChartSpec) -> pd.DataFrame:
    data = aggregate(df, spec)
    value = _value_label(spec)
    if spec.x and spec.color:
        return data.pivot_table(index=spec.x, columns=spec.color, values=value,
                                aggfunc="sum", fill_value=0)
    return data


# --------------------------------------------------------------------------- #
# Speichern / Exportieren
# --------------------------------------------------------------------------- #

def dashboard_to_json(name: str, charts: list[ChartSpec], filters: dict,
                      calculated: dict[str, str]) -> str:
    return json.dumps({
        "name": name,
        "charts": [c.to_dict() for c in charts],
        "filters": filters,
        "calculated_fields": calculated,
    }, indent=2, ensure_ascii=False, default=str)


def dashboard_from_json(text: str) -> tuple[str, list[ChartSpec], dict, dict]:
    data = json.loads(text)
    charts = [ChartSpec.from_dict(c) for c in data.get("charts", [])]
    return (data.get("name", "Dashboard"), charts, data.get("filters", {}),
            data.get("calculated_fields", {}))


def export_html(name: str, df: pd.DataFrame, charts: list[ChartSpec]) -> str:
    """Komplettes Dashboard als eigenständige, interaktive HTML-Datei."""
    blocks = []
    include_js = "cdn"
    for spec in charts:
        span = "full" if spec.width == "Voll" else "half"
        try:
            if spec.chart_type == "KPI":
                body = f'<div class="kpi">{format_number(kpi_value(df, spec))}</div>'
            elif spec.chart_type == "Tabelle":
                body = pivot_table(df, spec).to_html(classes="tbl", border=0)
            else:
                fig = build_figure(df, spec)
                body = fig.to_html(full_html=False, include_plotlyjs=include_js)
                include_js = False
        except Exception as exc:  # noqa: BLE001 - im Export nur anzeigen
            body = f"<p class='err'>Fehler: {exc}</p>"
        blocks.append(f'<section class="card {span}"><h2>{spec.title}</h2>{body}</section>')

    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f8fafc;color:#0f172a;margin:0;padding:24px}}
h1{{margin:0 0 16px}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:16px;overflow:auto}}
.card.full{{grid-column:1/-1}}
.card h2{{font-size:15px;color:#64748b;margin:0 0 8px;font-weight:600}}
.kpi{{font-size:44px;font-weight:700}}
.tbl{{border-collapse:collapse;font-size:13px;width:100%}}
.tbl th,.tbl td{{padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:right}}
.err{{color:#dc2626}}
@media (max-width:800px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>{name}</h1>
<div class="grid">{''.join(blocks)}</div>
</body></html>"""
