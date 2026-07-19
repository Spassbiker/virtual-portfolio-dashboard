"""Risiko- und Benchmark-Report für das virtuelle Depot.

Läuft als reines Shell-/Python-Modul (kein LLM-Turn), damit close_update.sh und
morning_run.sh es deterministisch mitlaufen lassen können. Drei Aufgaben:

  1) KONZENTRATIONS-CHECK: flaggt Klumpenrisiken, wenn eine Einzelposition mehr
     als MAX_POSITION_PCT oder ein Sektor mehr als MAX_SEKTOR_PCT des
     Portfoliowerts ausmacht. So fällt "6 Titel, aber faktisch eine Wette" sofort
     auf, statt sich still aufzubauen.

  2) KORRELATIONS-CHECK (Phase 5): misst 90-Tage-Kursverlauf-Korrelation
     zwischen allen Depot-Positionen. Ergänzt den Sektor-Check um die Fälle,
     die er blind für ist — zwei formal verschiedene Sektoren (z.B.
     Verteidigung + Luft-/Raumfahrt), die real im Gleichschritt laufen.

  3) BENCHMARK-VERGLEICH: misst die Depot-Gesamtrendite gegen DAX und MSCI World
     ab einem gemeinsamen Anker (beim ersten Lauf auf heute gesetzt). Läuft das
     Depot dauerhaft schlechter als der Index, ist das schwarz auf weiß sichtbar.

Ergebnisse werden nach depot_status.json unter depot["risiko"],
depot["korrelation"] und depot["benchmark"] geschrieben (für Dashboard +
Telegram-Zusammenfassung) und als kompakter Textblock ausgegeben (für Logs).
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

# Korrelations-Cluster (Phase 5): Paare über diesem Schwellwert gelten als
# "laufen im Gleichschritt"; Cluster über MAX_SEKTOR_PCT Portfolioanteil warnen.
CORR_THRESHOLD = 0.7
CORR_MIN_OBS = 15  # zu wenig gemeinsame Handelstage -> Korrelation verwerfen

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


def _pearson(a, b):
    n = len(a)
    if n < 2:
        return None
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((x - mean_b) ** 2 for x in b)
    if var_a <= 0 or var_b <= 0:
        return None
    return cov / (var_a * var_b) ** 0.5


def _daily_returns(isin):
    closes, _latest, _src = ticker_map.eur_history(isin, rng="3mo")
    if not closes or len(closes) < CORR_MIN_OBS + 1:
        return None
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]


def correlation_report(positions):
    """90-Tage-Korrelationscluster der Depot-Positionen (siehe Moduldoc Punkt 2).

    Liefert {"hinweise": [...], "cluster": [...]} — leer, wenn zu wenig
    Positionen/Historie für eine belastbare Aussage vorliegen.
    """
    if len(positions) < 2:
        return {"hinweise": [], "cluster": []}

    names = {}
    pos_value = {}
    returns = {}
    for p in positions:
        isin = p.get("isin")
        if not isin:
            continue
        names[isin] = p.get("wertpapier", isin)
        pos_value[isin] = p.get("boersenwert", 0) or 0
        rets = _daily_returns(isin)
        if rets:
            returns[isin] = rets

    isins = list(returns.keys())
    parent = {isin: isin for isin in isins}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(isins)):
        for j in range(i + 1, len(isins)):
            a, b = isins[i], isins[j]
            ra, rb = returns[a], returns[b]
            n = min(len(ra), len(rb))
            if n < CORR_MIN_OBS:
                continue
            c = _pearson(ra[-n:], rb[-n:])
            if c is not None and c > CORR_THRESHOLD:
                union(a, b)

    clusters = {}
    for isin in isins:
        clusters.setdefault(find(isin), []).append(isin)

    portfolio_value = sum(pos_value.values())
    hinweise = []
    cluster_reports = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        wert = sum(pos_value.get(m, 0) for m in members)
        anteil = wert / portfolio_value if portfolio_value else 0
        mitglieder = [names[m] for m in members]
        cluster_reports.append({"mitglieder": mitglieder, "anteil_pct": round(anteil * 100, 1)})
        if anteil > MAX_SEKTOR_PCT:
            hinweise.append(
                "⚠️ Korrelations-Cluster (%s) macht %.1f %% des Portfolios aus (>%.1f korreliert, Limit %.0f %%)"
                % (", ".join(mitglieder), anteil * 100, CORR_THRESHOLD, MAX_SEKTOR_PCT * 100))

    cluster_reports.sort(key=lambda c: -c["anteil_pct"])
    return {"hinweise": hinweise, "cluster": cluster_reports}


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


def format_lines(risiko, benchmark, korrelation=None):
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
    if korrelation and korrelation.get("hinweise"):
        lines.append("🔗 " + " · ".join(korrelation["hinweise"]))
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
    korrelation = correlation_report(positions)
    benchmark = benchmark_report(depot, gesamtvermoegen)

    depot["risiko"] = risiko
    depot["korrelation"] = korrelation
    depot["benchmark"] = benchmark
    data["depot"] = depot
    save_json(DEPOT_PATH, data)

    lines = format_lines(risiko, benchmark, korrelation)
    if lines:
        print("\n".join(lines))
    else:
        print("Risiko/Benchmark: keine Auffälligkeiten.")


if __name__ == "__main__":
    main()
