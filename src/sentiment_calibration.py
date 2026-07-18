"""Kalibrierung des KI-Sentiment-Signals: Score vs. tatsächlicher Kursverlauf.

Warum: Ohne diese Messung ist die Gewichtung von sentiment_score (±3) im
Scoring reine Annahme. Dieses Skript loggt bei jedem Lauf Score + Kurs (t0)
pro ISIN nach data/sentiment_history.jsonl, trägt nach ~5 Handelstagen den
Forward-Return nach und liefert einen einfachen Score↔Return-Report — damit
sich empirisch zeigt, ob ±3 die richtige Größenordnung ist oder ob das Signal
überhaupt Alpha bringt.

Kommandos:
  log       Heutigen Sentiment-Snapshot (Score + Kurs) anhängen (idempotent/Tag).
  backfill  Forward-Return für genug alte, noch offene Einträge nachtragen.
  report    Score-Bucket-Auswertung (Mittelwert-Return, Korrelation) ausgeben.

Reine Beobachtung — beeinflusst keine Trades, keine anderen Datendateien.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from paths import DATA_DIR, SENT as sentiment_path, load_json

HISTORY_PATH = os.path.join(DATA_DIR, "sentiment_history.jsonl")
FORWARD_DAYS = 5           # Handelstage bis Forward-Return gemessen wird
MIN_AGE_DAYS = 7           # Kalendertage-Proxy für "mind. 5 Handelstage vergangen"


def _read_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    records = []
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_history(records):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def cmd_log():
    """Heutigen Sentiment-Snapshot (Score + Kurs) anhängen. Pro ISIN+Tag nur einmal."""
    today = date.today().strftime("%Y-%m-%d")
    sentiment_data = load_json(sentiment_path, {"scores": {}})
    scores = sentiment_data.get("scores", {})
    if not scores:
        print("Keine sentiment_scores.json / keine Scores — nichts zu loggen.")
        return

    existing = _read_history()
    already = {(r["isin"], r["date"]) for r in existing}

    added = 0
    for isin, entry in scores.items():
        if (isin, today) in already:
            continue
        price, _src = ticker_map.eur_price(isin)
        if price is None:
            continue
        try:
            score = int(round(float(entry.get("sentiment_score", 0))))
        except (TypeError, ValueError):
            score = 0
        try:
            confidence = float(entry.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        existing.append({
            "date": today,
            "isin": isin,
            "sentiment_score": score,
            "confidence": round(confidence, 2),
            "event_kategorie": entry.get("event_kategorie") or "Sonstiges",
            "price_t0": price,
            "forward_return_5d": None,
        })
        added += 1

    _write_history(existing)
    print(f"Sentiment-Kalibrierung: {added} neue Einträge -> {HISTORY_PATH} "
          f"({len(existing)} gesamt).")


def cmd_backfill():
    """Trägt forward_return_5d für genug alte, noch offene Einträge nach."""
    records = _read_history()
    if not records:
        print("Keine Historie vorhanden.")
        return

    cutoff = date.today() - timedelta(days=MIN_AGE_DAYS)
    price_cache = {}
    filled = 0
    for r in records:
        if r.get("forward_return_5d") is not None:
            continue
        try:
            rec_date = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if rec_date > cutoff:
            continue  # noch nicht alt genug
        isin = r["isin"]
        if isin not in price_cache:
            price_cache[isin], _ = ticker_map.eur_price(isin)
        price_now = price_cache[isin]
        p0 = r.get("price_t0")
        if price_now is None or not p0:
            continue
        r["forward_return_5d"] = round((price_now - p0) / p0, 4)
        filled += 1

    _write_history(records)
    print(f"Backfill: {filled} Forward-Returns nachgetragen "
          f"({sum(1 for r in records if r.get('forward_return_5d') is not None)}/{len(records)} vollständig).")


def cmd_report():
    """Score-Bucket-Auswertung: Mittelwert-Return je Score + einfache Korrelation."""
    records = [r for r in _read_history() if r.get("forward_return_5d") is not None]
    if len(records) < 5:
        print(f"Nur {len(records)} vollständige Einträge — noch zu wenig für einen belastbaren Report "
              f"(braucht ein paar Tage Lauf, um Forward-Returns zu sammeln).")
        return

    buckets = {}
    for r in records:
        buckets.setdefault(r["sentiment_score"], []).append(r["forward_return_5d"])

    print(f"Sentiment-Kalibrierung: {len(records)} Einträge mit Forward-Return.\n")
    print(f"{'Score':>6} {'n':>5} {'Ø 5T-Return':>12}")
    for score in sorted(buckets):
        rets = buckets[score]
        avg = sum(rets) / len(rets)
        print(f"{score:>6} {len(rets):>5} {avg*100:>11.2f}%")

    # Einfache Pearson-Korrelation Score <-> Return (keine externen Deps).
    xs = [r["sentiment_score"] for r in records]
    ys = [r["forward_return_5d"] for r in records]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    varx = sum((x - mx) ** 2 for x in xs)
    vary = sum((y - my) ** 2 for y in ys)
    if varx > 0 and vary > 0:
        corr = cov / (varx ** 0.5 * vary ** 0.5)
        print(f"\nKorrelation Score↔5T-Return: {corr:+.3f} (n={n})")
    else:
        print("\nKorrelation nicht berechenbar (keine Varianz in Score oder Return).")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "log":
        cmd_log()
    elif cmd == "backfill":
        cmd_backfill()
    elif cmd == "report":
        cmd_report()
    else:
        print("Nutzung: python3 sentiment_calibration.py [log|backfill|report]")
        sys.exit(1)


if __name__ == "__main__":
    main()
