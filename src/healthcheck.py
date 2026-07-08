#!/usr/bin/env python3
"""Smoke-Test für den Portfolio-Workflow.

Prüft, dass JEDE Depotposition zu einem plausiblen EUR-Kurs auflösbar ist.
Schlägt ein Titel fehl (toter Ticker, falsches Instrument, kein EUR-Listing),
endet das Skript mit Exit-Code 1 und einem klaren Report — so fällt eine
Daten-/Ticker-Regression auf, BEVOR sie einen Fehl-Trade oder einen still
leerlaufenden Tageslauf verursacht.

Aufruf (z. B. am Anfang des täglichen Cron-Jobs):
    python3 src/healthcheck.py || echo "WARNUNG: Portfolio-Healthcheck fehlgeschlagen"
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map

base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
depot_path = os.path.join(base_dir, "depot_status.json")
chart_path = os.path.join(base_dir, "chartanalyse_ergebnisse.json")


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def chart_sma_map():
    sma = {}
    try:
        d = load(chart_path)
        for _, items in d.get("sektoren", {}).items():
            for it in items:
                if it.get("isin"):
                    sma[it["isin"]] = it.get("sma_50")
    except Exception:
        pass
    return sma


def main():
    depot = load(depot_path).get("depot", {})
    positions = depot.get("positionen", [])
    sma = chart_sma_map()

    failures = []
    ok = 0
    for p in positions:
        isin = p.get("isin")
        name = p.get("wertpapier", isin)

        # Eine gehaltene Position, die als "nicht handelbar" gilt, ist ein Fehler.
        if ticker_map.is_skipped(isin):
            failures.append(f"{name} ({isin}): im Depot, aber kein verlässliches EUR-Listing")
            continue

        price = None
        for cand in ticker_map.candidates(isin):
            pr, cur = ticker_map.fetch_price(cand)
            if pr is not None and cur == "EUR":
                price = pr
                break
        if price is None:
            failures.append(f"{name} ({isin}): kein EUR-Kurs auflösbar")
        elif not ticker_map.plausible(price, sma.get(isin)):
            failures.append(f"{name} ({isin}): Kurs {price} implausibel vs. SMA50 {sma.get(isin)}")
        else:
            ok += 1

    print(f"Healthcheck: {ok}/{len(positions)} Depotpositionen sauber bepreisbar.")
    if failures:
        print("FEHLGESCHLAGEN:")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)
    print("Alle Positionen OK. ✅")
    sys.exit(0)


if __name__ == "__main__":
    main()
