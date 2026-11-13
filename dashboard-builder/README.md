# Dashboard-Builder

Einfacher Dashboard-Builder im Stil von Tableau, in Python (Streamlit + Plotly + pandas).
Daten laden, per Klick Diagramme bauen, filtern, als Dashboard anordnen, speichern und als HTML teilen.

## Starten

```bash
cd dashboard-builder
uv run streamlit run app.py
```

Dann http://localhost:8501 öffnen.

## Funktionen

- **Datenquellen**: CSV (Komma oder Semikolon, deutsches Dezimalkomma), Excel, JSON, Parquet,
  oder die Beispieldaten aus `server/data/`. Verschachteltes JSON (z. B. Bestellpositionen) wird automatisch
  in Zeilen aufgelöst, Datumsfelder werden erkannt.
- **Dimensionen und Kennzahlen**: Felder werden wie in Tableau automatisch eingeteilt.
- **Diagrammtypen**: Balken, Balken horizontal, Linie, Fläche, Kreis, Streuung, Histogramm, Heatmap,
  Treemap, KPI-Kachel, Pivot-Tabelle.
- **Aggregation**: Summe, Mittelwert, Median, Anzahl, Anzahl eindeutig, Minimum, Maximum.
- **Datum gruppieren**: Tag, Woche, Monat, Quartal, Jahr.
- **Farbe / Aufteilen nach**: zweite Dimension für gestapelte Balken, mehrere Linien, Heatmap-Zeilen.
- **Sortierung und Top N**.
- **Berechnete Felder**: z. B. `Umsatz = `items.quantity` * `items.unit_price``.
- **Globale Filter**: Mehrfachauswahl, Zahlenbereich oder Datumsbereich; gelten für alle Diagramme.
- **Layout**: Diagramme halb oder voll breit, Reihenfolge verschieben, bearbeiten, löschen. KPIs stehen oben.
- **Speichern / Laden**: Dashboard-Definition als JSON.
- **Export**: das ganze Dashboard als eigenständige, interaktive HTML-Datei; gefilterte Daten als CSV.

## Aufbau

| Datei | Inhalt |
|---|---|
| `app.py` | Streamlit-Oberfläche |
| `dashboard_core.py` | Laden, Filtern, Aggregieren, Diagramme, Export (ohne Streamlit, testbar) |
| `tests/test_core.py` | Tests: `uv run pytest` |
