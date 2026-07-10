"""Risiko- und Benchmark-Report für das virtuelle Depot.

Läuft als reines Shell-/Python-Modul (kein LLM-Turn), damit close_update.sh und
morning_run.sh es deterministisch mitlaufen lassen können. Zwei Aufgaben:

  1) KONZENTRATIONS-CHECK: flaggt Klumpenrisiken, wenn eine Einzelposition mehr
     als MAX_POSITION_PCT oder ein Sektor mehr als MAX_SEKTOR_PCT des
     Portfoliowerts ausmacht. So fällt "6 Titel, aber faktisch eine Wette" sofort
     auf, statt sich still aufzubauen.

  2) BENCHMARK-VERGLEICH: misst die Depot-Gesamtrendite gegen DAX und MSCI World
     ab einem gemeinsamen Anker (beim ersten Lauf auf heute gesetzt). Läuft das
     Depot dauerhaft schlechter als der Index, ist das schwarz auf weiß sichtbar.

Ergebnisse werden nach depot_status.json unter depot["risiko"] und
depot["benchmark"] geschrieben (für Dashboard + Telegram-Zusammenfassung) und
als kompakter Textblock ausgegeben (für Logs).
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from paths import DEPOT as DEPOT_PATH, CHART as CHART_PATH, load_json, save_json

# Schwellen für die Klumpenrisiko-Warnung (Anteil am Portfoliowert).
MAX_POSITION_PCT = 0.20   # keine Einzelposition über 20 %
MAX_SEKTOR_PCT = 0.30     # kein Sektor über 30 %

# Benchmarks: DAX (Kursindex, EUR) und MSCI World über den EUR-ETF EUNL.DE
# (iShares Core MSCI World UCITS, Xetra) — passend zum EUR-denominierten Depot.
DAX_SYMBOL = "^GDAXI"
MSCI_SYMBOL = "EUNL.DE"


def load_sector_map():
    """ISIN -> Sektor aus der Chartanalyse; fehlt eine Zuordnung -> 'Sonstige'."""
    chart = load_json(CHART_PATH)
    if chart is None:
        return {}
    mapping = {}
    for sektor, items in chart.get("sektoren", {}).items():
        for item in items:
            if item.get("isin"):
                mapping.setdefault(item["isin"], sektor)
    return mapping


def concentration_report(positions, portfolio_value, sector_map):
    """Liefert (hinweise, top_position, top_sektor) als serialisierbares Dict."""
    hinweise = []
    if portfolio_value <= 0 or not positions:
        return {"hinweise": [], "positionen": [], "sektoren": []}

    # Einzelpositionen
    pos_anteile = []
    for p in positions:
        wert = p.get("boersenwert", 0) or 0
        anteil = wert / portfolio_value
        pos_anteile.append({
            "wertpapier": p.get("wertpapier", p.get("isin")),
            "isin": p.get("isin"),
            "anteil_pct": round(anteil * 100, 1),
        })
        if anteil > MAX_POSITION_PCT:
            hinweise.append(
                "⚠️ %s macht %.1f %% des Portfolios aus (Limit %.0f %%)"
                % (p.get("wertpapier", p.get("isin")), anteil * 100,
                   MAX_POSITION_PCT * 100))
    pos_anteile.sort(key=lambda x: -x["anteil_pct"])

    # Sektoren
    sektor_wert = {}
    for p in positions:
        sek = sector_map.get(p.get("isin"), "Sonstige")
        sektor_wert[sek] = sektor_wert.get(sek, 0) + (p.get("boersenwert", 0) or 0)
    sek_anteile = []
    for sek, wert in sektor_wert.items():
        anteil = wert / portfolio_value
        sek_anteile.append({"sektor": sek, "anteil_pct": round(anteil * 100, 1)})
        if anteil > MAX_SEKTOR_PCT:
            hinweise.append(
                "⚠️ Sektor %s macht %.1f %% des Portfolios aus (Limit %.0f %%)"
                % (sek, anteil * 100, MAX_SEKTOR_PCT * 100))
    sek_anteile.sort(key=lambda x: -x["anteil_pct"])

    return {
        "hinweise": hinweise,
        "positionen": pos_anteile,
        "sektoren": sek_anteile,
        "limits": {
            "position_pct": MAX_POSITION_PCT * 100,
            "sektor_pct": MAX_SEKTOR_PCT * 100,
        },
    }


def _index_level(symbol):
    price, _closes = ticker_map.fetch_index(symbol)
    return price


def benchmark_report(depot, gesamtvermoegen):
    """Vergleicht Depot-Gesamtrendite gegen DAX + MSCI World ab gemeinsamem Anker.

    Der Anker (Datum + Indexstände + Vermögen) wird beim ersten Lauf auf heute
    gesetzt und danach beibehalten. Return = Veränderung seit Anker in Prozent.
    """
    dax = _index_level(DAX_SYMBOL)
    msci = _index_level(MSCI_SYMBOL)

    bench = depot.get("benchmark", {}) or {}
    anker = bench.get("anker")

    # Anker beim ersten Lauf (oder wenn unvollständig) auf heute setzen.
    if not anker or not anker.get("vermoegen"):
        anker = {
            "datum": datetime.now().strftime("%Y-%m-%d"),
            "dax": round(dax, 2) if dax else None,
            "msci": round(msci, 4) if msci else None,
            "vermoegen": round(gesamtvermoegen, 2),
        }

    # Fehlende Anker-Indexstände nachtragen, sobald ein Kurs verfügbar ist
    # (Anker-Vermögen bleibt fix, damit der Startpunkt stabil ist).
    if anker.get("dax") is None and dax:
        anker["dax"] = round(dax, 2)
    if anker.get("msci") is None and msci:
        anker["msci"] = round(msci, 4)

    def pct(now, start):
        if now and start:
            return round((now - start) / start * 100, 2)
        return None

    depot_pct = pct(gesamtvermoegen, anker.get("vermoegen"))
    dax_pct = pct(dax, anker.get("dax"))
    msci_pct = pct(msci, anker.get("msci"))

    return {
        "anker": anker,
        "aktuell": {
            "dax": round(dax, 2) if dax else None,
            "msci": round(msci, 4) if msci else None,
            "vermoegen": round(gesamtvermoegen, 2),
        },
        "rendite_pct": {
            "depot": depot_pct,
            "dax": dax_pct,
            "msci_world": msci_pct,
        },
        "stand": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def format_lines(risiko, benchmark):
    """Kompakte Textzeilen für Telegram/Log. Leere Liste = alles im Rahmen."""
    lines = []
    r = benchmark.get("rendite_pct", {})
    if any(v is not None for v in r.values()):
        def s(v):
            return "%+.2f%%" % v if v is not None else "n/a"
        lines.append(
            "📈 Seit %s — Depot %s | DAX %s | MSCI World %s"
            % (benchmark.get("anker", {}).get("datum", "?"),
               s(r.get("depot")), s(r.get("dax")), s(r.get("msci_world"))))
    hinweise = risiko.get("hinweise", [])
    if hinweise:
        lines.append("🚨 Klumpenrisiko: " + " · ".join(hinweise))
    return lines


def main():
    data = load_json(DEPOT_PATH, {})
    depot = data.get("depot", {})
    positions = depot.get("positionen", [])
    portfolio_value = depot.get("portfoliowert", 0) or sum(
        p.get("boersenwert", 0) for p in positions)
    gesamtvermoegen = depot.get("gesamtvermoegen", portfolio_value)

    sector_map = load_sector_map()
    risiko = concentration_report(positions, portfolio_value, sector_map)
    benchmark = benchmark_report(depot, gesamtvermoegen)

    depot["risiko"] = risiko
    depot["benchmark"] = benchmark
    data["depot"] = depot
    save_json(DEPOT_PATH, data)

    lines = format_lines(risiko, benchmark)
    if lines:
        print("\n".join(lines))
    else:
        print("Risiko/Benchmark: keine Auffälligkeiten.")


if __name__ == "__main__":
    main()
