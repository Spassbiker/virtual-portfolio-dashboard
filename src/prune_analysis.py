"""Chart-, Fundamental- und Sentiment-Analyse auf tatsächlich relevante Wertpapiere beschränken.

Vorgabe: eine Position bleibt nur dann in den Analyse-JSONs, wenn sie
**im Depot** steckt oder **explizit als Kaufkandidatin geführt wird**.

- `data/chartanalyse_ergebnisse.json`: keep if `isin ∈ Depot` ODER
  `empfehlung.lower() == "kaufen"`. Nicht handelbare (kein EUR-Listing),
  Platzhalter und Delistings fliegen ebenfalls raus.
- `data/fundamentalanalyse_ergebnisse.json`: keep if `isin ∈ Depot` ODER
  `bewertung.lower() == "attraktiv"`. Platzhalter und Delistings raus.
- `data/sentiment_scores.json`: nur ISINs behalten, die nach dem Prune
  noch in Chart ODER Fundamental existieren — sonst zeigt das Dashboard
  Sentiment-Waisen ohne Namen ("?").
- `data/news_raw.json`: analog auf die verbleibende ISIN-Menge beschränken.

Depot-Positionen sind IMMER geschützt.
"""

import json
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CHART = os.path.join(BASE, "data", "chartanalyse_ergebnisse.json")
FUNDA = os.path.join(BASE, "data", "fundamentalanalyse_ergebnisse.json")
DEPOT = os.path.join(BASE, "data", "depot_status.json")
SENT = os.path.join(BASE, "data", "sentiment_scores.json")
NEWS = os.path.join(BASE, "data", "news_raw.json")

PLACEHOLDER = ("vervollständigung", "ergänzt zur", "platzhalter")
DELISTED = ("börse genommen", "delisted", "delisting")
NO_LISTING = ("kein verlässliches eur-listing", "nicht handelbar")


def contains(text, markers):
    t = (text or "").lower()
    return any(m in t for m in markers)


def should_drop_chart(item, depot_isins):
    if item.get("isin") in depot_isins:
        return None
    text = item.get("begruendung") or ""
    if contains(text, PLACEHOLDER):
        return "Platzhalter"
    if contains(text, DELISTED):
        return "delisted"
    if contains(text, NO_LISTING):
        return "nicht handelbar (kein EUR-Listing)"
    if (item.get("empfehlung") or "").lower() != "kaufen":
        return f"empfehlung={item.get('empfehlung') or '?'} (kein Kaufkandidat)"
    return None


def should_drop_funda(item, depot_isins):
    if item.get("isin") in depot_isins:
        return None
    text = item.get("begruendung") or ""
    if contains(text, PLACEHOLDER):
        return "Platzhalter"
    if contains(text, DELISTED):
        return "delisted"
    if (item.get("bewertung") or "").lower() != "attraktiv":
        return f"bewertung={item.get('bewertung') or '?'} (kein Kaufkandidat)"
    return None


def prune_analysis(path, depot_isins, drop_fn, label):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    dropped = []
    for sec, items in list(data.get("sektoren", {}).items()):
        kept = []
        for item in items:
            reason = drop_fn(item, depot_isins)
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
    print(f"Sentiment: {len(orphans)} Waisen entfernt ({orphans})")


def sync_news(relevant_isins):
    """news_raw.json hat die Form {generated_at, items: {ISIN: [...]}}.
    Nur den items-Teilbaum säubern; Metadaten unangetastet lassen."""
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

    prune_analysis(CHART, depot_isins, should_drop_chart, "Chart")
    prune_analysis(FUNDA, depot_isins, should_drop_funda, "Fundamental")

    relevant = collect_isins(CHART) | collect_isins(FUNDA) | depot_isins
    sync_sentiment(relevant)
    sync_news(relevant)


if __name__ == "__main__":
    main()
