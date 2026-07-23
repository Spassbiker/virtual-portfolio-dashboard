#!/usr/bin/env python3
"""Täglicher Vermögens-Logger für die Equity-Kurve im Dashboard (V1).

Hängt pro Handelstag eine Zeile an data/vermoegen_history.json an:
Gesamtvermögen Aktien-Depot + ETF-Sleeve sowie die Benchmark-Stände
(DAX, MSCI World) aus depot_status.json. Idempotent: ein zweiter Lauf am
selben Tag (17:35-Close-Update) ÜBERSCHREIBT die Tageszeile, statt sie zu
doppeln — die Kurve zeigt damit abends den Schlussstand.

Beim allerersten Lauf wird zusätzlich der Benchmark-Anker (09.07.) als
Startpunkt eingetragen, damit die Kurve am selben Punkt beginnt wie der
bestehende Performance-Vergleich. Für den Anker-Tag ist kein ETF-Stand
überliefert → etf_gesamt bleibt dort null, die ETF-Linie beginnt später.

Reine Beobachtung: liest depot_status.json, schreibt nur die History-Datei,
beeinflusst keine Trades.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import DEPOT, VERMOEGEN_HISTORY, load_json, save_json


def build_entry(depot_data, datum):
    """Tageszeile aus dem aktuellen depot_status.json ableiten."""
    d = depot_data.get("depot", {})
    e = depot_data.get("etf_depot", {})
    bench_akt = (d.get("benchmark") or {}).get("aktuell") or {}
    return {
        "datum": datum,
        "depot_gesamt": round(d.get("gesamtvermoegen", 0), 2),
        "etf_gesamt": round(e.get("gesamtvermoegen", 0), 2),
        "cash_depot": round(d.get("aktueller_barbestand", 0), 2),
        "cash_etf": round(e.get("aktueller_barbestand", 0), 2),
        "dax": bench_akt.get("dax"),
        "msci": bench_akt.get("msci"),
    }


def anchor_entry(depot_data):
    """Benchmark-Anker als Startpunkt der Kurve (nur beim ersten Lauf)."""
    anker = (depot_data.get("depot", {}).get("benchmark") or {}).get("anker") or {}
    if not anker.get("datum"):
        return None
    return {
        "datum": anker["datum"],
        "depot_gesamt": anker.get("vermoegen"),
        "etf_gesamt": None,
        "cash_depot": None,
        "cash_etf": None,
        "dax": anker.get("dax"),
        "msci": anker.get("msci"),
    }


def upsert(history, entry):
    """Zeile für entry['datum'] ersetzen oder chronologisch einfügen."""
    rows = [r for r in history if r.get("datum") != entry["datum"]]
    rows.append(entry)
    rows.sort(key=lambda r: r.get("datum") or "")
    return rows


def main():
    depot_data = load_json(DEPOT)
    if not depot_data or "depot" not in depot_data:
        print("FEHLER: depot_status.json fehlt oder ist leer", file=sys.stderr)
        return 1

    data = load_json(VERMOEGEN_HISTORY, default={"history": []})
    history = data.get("history", [])

    if not history:
        anker = anchor_entry(depot_data)
        if anker:
            history = upsert(history, anker)

    today = datetime.date.today().isoformat()
    history = upsert(history, build_entry(depot_data, today))

    save_json(VERMOEGEN_HISTORY, {"history": history})
    print(f"Vermögens-History: {len(history)} Tage, Stand {today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
