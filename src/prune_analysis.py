"""Chart-, Fundamental- und Sentiment-Analyse auf sinnvolle Menge reduzieren.

Regeln:

1. **Rauschen raus**: Platzhalter-Einträge ("Ergänzt zur Vervollständigung …"),
   Delistings, nicht handelbare Werte ("Kein verlässliches EUR-Listing") und
   Cross-Sektor-Duplikate ohne Zusatznutzen werden verworfen.
2. **Depot-Schutz**: eine ISIN aus dem Depot bleibt IMMER in Chart und Funda.
3. **Sektor-Minimum**: jeder Sektor soll mindestens `TARGET_PER_SECTOR = 10`
   Wertpapiere zeigen, sofern das Universum genügend hergibt. Priorität pro
   Sektor: Depot > Kaufen > Halten > Verkaufen. Wenn ein Sektor mehr als 10
   Kandidaten hat, werden die schwächsten weggelassen. Weniger als 10 bleiben
   unangetastet — auffüllen kann nur der wöchentliche Fundamental-Refresh.
4. **Handelbarkeitsfilter Funda**: eine Funda-Position ohne Chart-Eintrag
   (kein EUR-Listing) fliegt raus — sie ist nicht handelbar.
5. **Sentiment/News**: nach dem Prune auf ISINs beschränken, die in Chart
   oder Funda existieren, damit das Dashboard keine „?"-Waisen zeigt.
"""

import json
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CHART = os.path.join(BASE, "data", "chartanalyse_ergebnisse.json")
FUNDA = os.path.join(BASE, "data", "fundamentalanalyse_ergebnisse.json")
DEPOT = os.path.join(BASE, "data", "depot_status.json")
SENT = os.path.join(BASE, "data", "sentiment_scores.json")
NEWS = os.path.join(BASE, "data", "news_raw.json")

TARGET_PER_SECTOR = 10

PLACEHOLDER = ("vervollständigung", "ergänzt zur", "platzhalter")
DELISTED = ("börse genommen", "delisted", "delisting")
NO_LISTING = ("kein verlässliches eur-listing", "nicht handelbar")


def contains(text, markers):
    t = (text or "").lower()
    return any(m in t for m in markers)


def is_chart_noise(item):
    text = item.get("begruendung") or ""
    if contains(text, PLACEHOLDER):
        return "Platzhalter"
    if contains(text, DELISTED):
        return "delisted"
    if contains(text, NO_LISTING):
        return "nicht handelbar (kein EUR-Listing)"
    return None


def is_funda_noise(item):
    text = item.get("begruendung") or ""
    if contains(text, PLACEHOLDER):
        return "Platzhalter"
    if contains(text, DELISTED):
        return "delisted"
    return None


def chart_priority(item, depot_isins):
    """0 = beste. Depot > Kaufen > Halten > Verkaufen > sonstige."""
    if item.get("isin") in depot_isins:
        return 0
    sig = (item.get("signal") or item.get("empfehlung") or "").lower()
    if "kauf" in sig:
        return 1
    if "halt" in sig:
        return 2
    if "verkauf" in sig:
        return 3
    return 4


def funda_priority(item, depot_isins):
    if item.get("isin") in depot_isins:
        return 0
    bew = (item.get("bewertung") or "").lower()
    emp = (item.get("empfehlung") or "").lower()
    if "attraktiv" in bew:
        return 1
    if emp == "kaufen":
        return 1
    if "neutral" in bew:
        return 2
    if "spekulativ" in bew or emp == "verkaufen":
        return 4
    return 3


def prune_chart(depot_isins):
    with open(CHART, "r", encoding="utf-8") as f:
        data = json.load(f)

    dropped = []
    for sec, items in list(data.get("sektoren", {}).items()):
        # Rauschen raus (Depot ist immer sicher – kein Rauschen möglich).
        cleaned = []
        for it in items:
            noise = None if it.get("isin") in depot_isins else is_chart_noise(it)
            if noise:
                dropped.append((sec, it.get("wertpapier", "?"), noise))
            else:
                cleaned.append(it)

        # Duplikate pro Sektor entfernen (ISIN als Schlüssel; erste Instanz gewinnt).
        seen = set()
        deduped = []
        for it in cleaned:
            isin = it.get("isin")
            if isin and isin in seen:
                dropped.append((sec, it.get("wertpapier", "?"), "Duplikat"))
                continue
            seen.add(isin)
            deduped.append(it)

        # Sektor-Trim: wenn >TARGET, die schwächsten (nach Priorität) weglassen.
        deduped.sort(key=lambda it: (chart_priority(it, depot_isins), it.get("wertpapier", "")))
        if len(deduped) > TARGET_PER_SECTOR:
            for it in deduped[TARGET_PER_SECTOR:]:
                dropped.append((sec, it.get("wertpapier", "?"),
                                f"Sektor-Kap ({TARGET_PER_SECTOR}), niedrige Priorität"))
            deduped = deduped[:TARGET_PER_SECTOR]

        data["sektoren"][sec] = deduped

    with open(CHART, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Chart: {len(dropped)} Positionen entfernt")
    for sec, name, reason in dropped:
        print(f"  [{sec}] {name} → {reason}")
    for sec, items in data["sektoren"].items():
        print(f"  Sektor '{sec}': {len(items)} Positionen")


def prune_funda(depot_isins, chart_isins):
    with open(FUNDA, "r", encoding="utf-8") as f:
        data = json.load(f)

    dropped = []
    for sec, items in list(data.get("sektoren", {}).items()):
        cleaned = []
        for it in items:
            if it.get("isin") in depot_isins:
                cleaned.append(it)
                continue
            noise = is_funda_noise(it)
            if noise:
                dropped.append((sec, it.get("wertpapier", "?"), noise))
                continue
            if it.get("isin") not in chart_isins:
                dropped.append((sec, it.get("wertpapier", "?"), "nicht in Chart (nicht handelbar)"))
                continue
            cleaned.append(it)

        seen = set()
        deduped = []
        for it in cleaned:
            isin = it.get("isin")
            if isin and isin in seen:
                dropped.append((sec, it.get("wertpapier", "?"), "Duplikat"))
                continue
            seen.add(isin)
            deduped.append(it)

        deduped.sort(key=lambda it: (funda_priority(it, depot_isins), it.get("wertpapier", "")))
        if len(deduped) > TARGET_PER_SECTOR:
            for it in deduped[TARGET_PER_SECTOR:]:
                dropped.append((sec, it.get("wertpapier", "?"),
                                f"Sektor-Kap ({TARGET_PER_SECTOR}), niedrige Priorität"))
            deduped = deduped[:TARGET_PER_SECTOR]

        data["sektoren"][sec] = deduped

    with open(FUNDA, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Fundamental: {len(dropped)} Positionen entfernt")
    for sec, name, reason in dropped:
        print(f"  [{sec}] {name} → {reason}")
    for sec, items in data["sektoren"].items():
        print(f"  Sektor '{sec}': {len(items)} Positionen")


def collect_isins(path):
    data = json.load(open(path, encoding="utf-8"))
    return {i.get("isin") for sec in data.get("sektoren", {}).values() for i in sec if i.get("isin")}


def sync_sentiment(relevant_isins):
    if not os.path.exists(SENT):
        return
    data = json.load(open(SENT, encoding="utf-8"))
    scores = data.get("scores", {})
    orphans = [i for i in scores if i not in relevant_isins]
    for isin in orphans:
        scores.pop(isin, None)
    with open(SENT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Sentiment: {len(orphans)} Waisen entfernt")


def sync_news(relevant_isins):
    if not os.path.exists(NEWS):
        return
    data = json.load(open(NEWS, encoding="utf-8"))
    items = data.get("items")
    if not isinstance(items, dict):
        print("News: unbekanntes Format, übersprungen")
        return
    orphans = [i for i in list(items.keys()) if i not in relevant_isins]
    for isin in orphans:
        items.pop(isin, None)
    with open(NEWS, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"News: {len(orphans)} Waisen entfernt")


def main():
    depot = json.load(open(DEPOT, encoding="utf-8"))
    depot_isins = {p.get("isin") for p in depot.get("depot", {}).get("positionen", []) if p.get("isin")}
    print(f"Depot-Schutz: {len(depot_isins)} ISINs")
    print(f"Sektor-Ziel: min. {TARGET_PER_SECTOR} pro Sektor (wenn Universum reicht)")
    print()

    prune_chart(depot_isins)
    print()
    chart_isins = collect_isins(CHART)
    prune_funda(depot_isins, chart_isins)

    relevant = chart_isins | collect_isins(FUNDA) | depot_isins
    print()
    sync_sentiment(relevant)
    sync_news(relevant)


if __name__ == "__main__":
    main()
