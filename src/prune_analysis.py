"""Chart- und Fundamentalanalyse auf tatsächlich relevante Wertpapiere beschränken.

Regel (Vorgabe): eine Position bleibt nur dann in
`chartanalyse_ergebnisse.json` bzw. `fundamentalanalyse_ergebnisse.json`,
wenn sie **im Depot** steckt oder **echte Recherche-Belege** trägt, die sie
als Kaufkandidatin qualifizieren. Konkret fliegen raus:

- Platzhalter-Einträge ("Ergänzt zur Vervollständigung ...", "Platzhalter") —
  reines Sektorfüller-Rauschen.
- Delistete Papiere ("Von der Börse genommen").
- Chart-Positionen mit Text "Kein verlässliches EUR-Listing" (nicht handelbar).

Depot-Positionen sind IMMER geschützt — die dürfen nie stillschweigend aus
der Analyse verschwinden, selbst wenn die aktuelle Recherche mager ist.
"""

import json
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CHART = os.path.join(BASE, "data", "chartanalyse_ergebnisse.json")
FUNDA = os.path.join(BASE, "data", "fundamentalanalyse_ergebnisse.json")
DEPOT = os.path.join(BASE, "data", "depot_status.json")

PLACEHOLDER = ("vervollständigung", "ergänzt zur", "platzhalter")
DELISTED = ("börse genommen", "delisted", "delisting")
NO_LISTING = ("kein verlässliches eur-listing", "nicht handelbar")


def contains(text, markers):
    t = (text or "").lower()
    return any(m in t for m in markers)


def should_drop(item, depot_isins):
    if item.get("isin") in depot_isins:
        return None  # Depot-Position ist geschützt
    text = item.get("begruendung") or ""
    emp = (item.get("empfehlung") or "").lower()
    if contains(text, PLACEHOLDER):
        return "Platzhalter"
    if contains(text, DELISTED) or emp == "n/a":
        # Delisted oder ohne belastbares Rating und nicht im Depot → weg
        return "delisted/kein Rating"
    if contains(text, NO_LISTING):
        return "nicht handelbar (kein EUR-Listing)"
    return None


def prune(path, depot_isins, label):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    dropped = []
    for sec, items in list(data.get("sektoren", {}).items()):
        kept = []
        for item in items:
            reason = should_drop(item, depot_isins)
            if reason is None:
                kept.append(item)
            else:
                dropped.append((sec, item.get("wertpapier", "?"), reason))
        data["sektoren"][sec] = kept

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"{label}: {len(dropped)} Positionen entfernt")
    for sec, name, reason in dropped:
        print(f"  [{sec}] {name} → {reason}")
    return dropped


def main():
    depot = json.load(open(DEPOT, encoding="utf-8"))
    depot_isins = {p.get("isin") for p in depot.get("depot", {}).get("positionen", []) if p.get("isin")}
    print(f"Depot-Schutz: {len(depot_isins)} ISINs")

    prune(CHART, depot_isins, "Chart")
    prune(FUNDA, depot_isins, "Fundamental")


if __name__ == "__main__":
    main()
