"""Räume irreführende Empfehlungen in der Fundamentalanalyse auf.

Zwei Klassen von Datenfehlern werden neutralisiert:

1. **Platzhalter-Einträge** ("Ergänzt zur Vervollständigung ...") haben zwar keine
   echten Kennzahlen recherchiert, tragen aber trotzdem ein `empfehlung`-Feld
   (oft "Kaufen"/"Halten"/"Verkaufen"). Das Score-Modell in `update_depot.py`
   ignoriert diese Einträge bereits (siehe `is_funda_placeholder`), aber die
   Dashboard-Anzeige zeigt die erfundene Empfehlung. Wir setzen sie auf "N/A".

2. **Delistete Werte** (Text enthält "Börse genommen" / "delisted") mit
   aktivem `empfehlung=Kaufen` etc. — hier ist die Empfehlung schlicht falsch,
   das Papier ist nicht mehr handelbar. Ebenfalls auf "N/A".

Es werden KEINE inhaltlichen Begründungstexte geändert; für frische
qualitative Aussagen (Marktposition, Auftragslage) braucht es einen
LLM-Refresh, der separat gepflegt wird.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import FUNDA as FUNDA_PATH, load_json, save_json

PLACEHOLDER_MARKERS = ("vervollständigung", "ergänzt zur", "platzhalter")
DELISTED_MARKERS = ("börse genommen", "delisted", "delisting")


def is_placeholder(text):
    t = (text or "").lower()
    return any(m in t for m in PLACEHOLDER_MARKERS)


def is_delisted(text):
    t = (text or "").lower()
    return any(m in t for m in DELISTED_MARKERS)


def sanitize_item(item):
    text = item.get("begruendung", "")
    reasons = []
    if is_placeholder(text) and (item.get("empfehlung") or "").lower() not in ("", "n/a"):
        item["empfehlung"] = "N/A"
        reasons.append("Platzhalter → empfehlung=N/A")
    if is_delisted(text) and (item.get("empfehlung") or "").lower() not in ("", "n/a"):
        item["empfehlung"] = "N/A"
        reasons.append("delisted → empfehlung=N/A")
    return reasons


def main():
    data = load_json(FUNDA_PATH, {})

    changes = []
    for sector, items in data.get("sektoren", {}).items():
        for item in items:
            reasons = sanitize_item(item)
            if reasons:
                changes.append((sector, item.get("wertpapier", "?"), reasons))

    save_json(FUNDA_PATH, data)

    if changes:
        print(f"Fundamentals sanitisiert: {len(changes)} Einträge korrigiert")
        for sec, name, reasons in changes:
            print(f"  [{sec}] {name}: {'; '.join(reasons)}")
    else:
        print("Fundamentals OK — keine Änderungen nötig.")


if __name__ == "__main__":
    main()
