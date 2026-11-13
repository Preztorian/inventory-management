from pathlib import Path

import pandas as pd
import pytest

import dashboard_core as core
from dashboard_core import ChartSpec

DATA = Path(__file__).resolve().parents[2] / "server" / "data"


@pytest.fixture
def orders():
    df = core.load_file("orders.json", (DATA / "orders.json").read_bytes())
    return core.add_calculated_field(df, "Umsatz", "`items.quantity` * `items.unit_price`")


def test_nested_items_are_exploded(orders):
    assert "items.sku" in orders.columns
    assert pd.api.types.is_datetime64_any_dtype(orders["order_date"])
    assert "Umsatz" in core.measures(orders)


def test_csv_with_semicolon_and_comma_decimal():
    df = core.load_file("x.csv", "a;b\nx;1,5\ny;2,5\n".encode())
    assert df["b"].sum() == 4.0


def test_aggregate_sum_matches_pandas(orders):
    spec = ChartSpec(chart_type="Balken", x="warehouse", y="Umsatz", agg="Summe")
    res = core.aggregate(orders, spec)
    expected = orders.groupby("warehouse")["Umsatz"].sum()
    assert res.set_index("warehouse")["Summe(Umsatz)"].to_dict() == pytest.approx(expected.to_dict())
    assert list(res["Summe(Umsatz)"]) == sorted(res["Summe(Umsatz)"], reverse=True)


def test_date_grain_and_top_n(orders):
    monthly = core.aggregate(orders, ChartSpec(x="order_date", date_grain="Monat"))
    assert monthly["order_date"].dt.day.eq(1).all()
    top = core.aggregate(orders, ChartSpec(x="customer", y="Umsatz", top_n=3))
    assert len(top) == 3


def test_filters(orders):
    out = core.apply_filters(orders, {"warehouse": {"values": ["Tokyo"]},
                                      "order_date": {"range": ["2025-01-01", "2025-03-31"]}})
    assert set(out["warehouse"]) == {"Tokyo"}
    assert out["order_date"].max() < pd.Timestamp("2025-04-01")


@pytest.mark.parametrize("ctype", [c for c in core.CHART_TYPES if c not in ("KPI", "Tabelle")])
def test_every_chart_type_builds(orders, ctype):
    spec = ChartSpec(chart_type=ctype, x="category", y="Umsatz", color="status")
    assert core.build_figure(orders, spec) is not None


def test_kpi_and_roundtrip(orders):
    spec = ChartSpec(chart_type="KPI", y="order_number", agg="Anzahl eindeutig")
    assert core.kpi_value(orders, spec) == orders["order_number"].nunique()
    text = core.dashboard_to_json("D", [spec], {"warehouse": {"values": ["Tokyo"]}}, {"U": "a*b"})
    name, charts, filters, calc = core.dashboard_from_json(text)
    assert (name, charts[0].chart_type, calc) == ("D", "KPI", {"U": "a*b"})
    html = core.export_html("D", orders, [spec, ChartSpec(x="warehouse")])
    assert "<h1>D</h1>" in html and "plotly" in html
