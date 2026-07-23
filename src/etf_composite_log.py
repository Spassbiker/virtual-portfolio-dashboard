"""Kalibrierung des ETF-Composite-Scores: Score vs. tatsächlicher Kursverlauf.

Pendant zu sentiment_calibration.py für den ETF-Sleeve: Ohne Messung ist die
Composite-Gewichtung (Momentum/Risiko/Sentiment/Struktur) und die 70er-
Kaufschwelle reine Annahme. Loggt pro Lauf Composite + Bucket + Kurs (t0) je
ISIN nach data/etf_composite_history.jsonl, trägt nach ~5 Handelstagen den
Forward-Return nach und liefert einen Bucket-/Korrelations-Report.

Kommandos:
  log       Heutigen Composite-Snapshot anhängen (idempotent pro ISIN+Tag).
  backfill  Forward-Return für genug alte, noch offene Einträge nachtragen.
  report    Composite-Bucket-Auswertung (Ø-Return, Korrelation) ausgeben.

Reine Beobachtung — beeinflusst keine Trades, keine anderen Datendateien.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from paths import DATA_DIR, ETF_RANKING, load_json

HISTORY_PATH = os.path.join(DATA_DIR, "etf_composite_history.jsonl")
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


def _best_rows_by_isin():
    """Pro ISIN die Ranking-Zeile mit dem höchsten Composite (ein ETF kann in
    mehreren Themen-Sektoren gelistet sein — geloggt wird das Signal, auf das
    die Engine kauft)."""
    ranking = load_json(ETF_RANKING, {})
    best = {}
    for _sektor, rows in ranking.get("sektoren", {}).items():
        for row in rows:
            isin = row.get("isin")
            if not isin or row.get("composite") is None:
                continue
            cur = best.get(isin)
            if cur is None or row.get("composite", 0) > cur.get("composite", 0):
                best[isin] = row
    return best


def cmd_log():
    today = date.today().strftime("%Y-%m-%d")
    best = _best_rows_by_isin()
    if not best:
        print("Kein etf_ranking.json / keine Composites — nichts zu loggen.")
        return

    existing = _read_history()
    already = {(r["isin"], r["date"]) for r in existing}

    added = 0
    for isin, row in best.items():
        if (isin, today) in already:
            continue
        price, _src = ticker_map.eur_price(isin)
        if price is None:
            continue
        existing.append({
            "date": today,
            "isin": isin,
            "composite": row.get("composite"),
            "bucket": row.get("bucket"),
            "price_t0": price,
            "forward_return_5d": None,
        })
        added += 1

    _write_history(existing)
    print(f"ETF-Composite-Kalibrierung: {added} neue Einträge -> {HISTORY_PATH} "
          f"({len(existing)} gesamt).")


def cmd_backfill():
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
            continue
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
    records = [r for r in _read_history() if r.get("forward_return_5d") is not None]
    if len(records) < 10:
        print(f"Nur {len(records)} vollständige Einträge — noch zu wenig für einen belastbaren Report.")
        return

    buckets = {}
    for r in records:
        buckets.setdefault(r.get("bucket") or "?", []).append(r["forward_return_5d"])

    print(f"ETF-Composite-Kalibrierung: {len(records)} Einträge mit Forward-Return.\n")
    print(f"{'Bucket':>12} {'n':>5} {'Ø 5T-Return':>12}")
    for bucket in ("CORE", "SATELLITE", "BEOBACHTEN", "MEIDEN", "?"):
        rets = buckets.get(bucket)
        if not rets:
            continue
        avg = sum(rets) / len(rets)
        print(f"{bucket:>12} {len(rets):>5} {avg*100:>11.2f}%")

    xs = [r["composite"] for r in records if r.get("composite") is not None]
    ys = [r["forward_return_5d"] for r in records if r.get("composite") is not None]
    n = len(xs)
    if n >= 10:
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        varx = sum((x - mx) ** 2 for x in xs)
        vary = sum((y - my) ** 2 for y in ys)
        if varx > 0 and vary > 0:
            corr = cov / (varx ** 0.5 * vary ** 0.5)
            print(f"\nKorrelation Composite↔5T-Return: {corr:+.3f} (n={n})")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "log":
        cmd_log()
    elif cmd == "backfill":
        cmd_backfill()
    elif cmd == "report":
        cmd_report()
    else:
        print("Nutzung: python3 etf_composite_log.py [log|backfill|report]")
        sys.exit(1)


if __name__ == "__main__":
    main()
