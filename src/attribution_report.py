"""Performance-Attribution seit dem Benchmark-Anker.

Beantwortet die Frage, die Benchmark-Zahlen allein nicht beantworten: WO kommt
die Über-/Underperformance her? Pro ISIN wird der ökonomische Beitrag im
Fenster [Anker, heute] rekonstruiert:

    Beitrag = (Wert_heute − Wert_am_Anker) + Verkaufserlöse − Kaufkosten

mit Wert_am_Anker = (damals gehaltene Stücke) × (Kurs am Ankertag). Die
Stückzahl am Anker wird aus der Transaktionshistorie zurückgerechnet, Erlöse/
Kosten kommen netto (inkl. Gebühren + Steuern) aus den Transaktionen. Die
Summe der Beiträge entspricht damit der Vermögensänderung des Sleeves im
Fenster. Zusätzlich: Kosten-Drag (Gebühren/Steuern) und ein Whipsaw-Check
(Verkäufe, deren Kurs seitdem deutlich gestiegen ist = zu früh verkauft).

Read-only bis auf den Report: schreibt docs/attribution/YYYY-MM-DD.md.

Nutzung:  python3 src/attribution_report.py [--anchor YYYY-MM-DD]
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from paths import BASE, DEPOT, load_json

REPORT_DIR = os.path.join(BASE, "docs", "attribution")
WHIPSAW_MIN_REBOUND = 0.03   # Verkauf gilt als "zu früh", wenn Kurs seitdem > +3%


def eur_history_dated(isin, rng="3mo"):
    """[(date, close_eur), ...] oldest-first — wie ticker_map.eur_history,
    aber mit echten Handelstags-Daten (für den Anker-Lookup)."""
    def fetch(ticker):
        try:
            data = ticker_map._http(
                f"https://query1.finance.yahoo.com/v8/finance/chart/"
                f"{ticker}?interval=1d&range={rng}")
            result = data["chart"]["result"][0]
            meta = result["meta"]
            if meta.get("instrumentType") not in ticker_map.VALID_INSTRUMENT_TYPES:
                return None, None
            stamps = result.get("timestamp", [])
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            out = []
            for t, c in zip(stamps, closes):
                if c is not None:
                    out.append((datetime.date.fromtimestamp(t), c))
            return out, meta.get("currency", "")
        except Exception:
            return None, None

    for cand in ticker_map.candidates(isin):
        series, cur = fetch(cand)
        if series and cur == "EUR":
            return series
    usd_t = ticker_map.USD_TICKER.get(isin)
    if usd_t:
        series, cur = fetch(usd_t)
        rate = ticker_map.usd_to_eur_rate()
        if series and cur == "USD" and rate:
            return [(d, round(c * rate, 4)) for d, c in series]
    return None


def price_at(series, target):
    """Letzter Close am/vor dem Zieldatum (None, wenn Serie vorher endet)."""
    best = None
    for d, c in series:
        if d <= target:
            best = c
        else:
            break
    return best


def attribute_sleeve(sleeve, anchor_date, today, price_cache):
    """Liste von Beiträgen pro ISIN + Kostensummen für ein Depot-Sleeve."""
    positions = {p["isin"]: p for p in sleeve.get("positionen", [])}
    txs = [t for t in sleeve.get("transaktionshistorie", [])
           if anchor_date < _d(t.get("datum")) <= today]

    isins = set(positions) | {t.get("isin") for t in txs if t.get("isin")}
    rows = []
    fees = taxes = 0.0
    whipsaws = []

    for isin in sorted(isins):
        p = positions.get(isin)
        units_now = p.get("stueck", 0) if p else 0
        price_now = (p.get("boersenkurs") or 0) if p else 0.0
        name = (p or {}).get("wertpapier") or next(
            (t.get("wertpapier") for t in txs if t.get("isin") == isin), isin)

        buys = [t for t in txs if t.get("isin") == isin and t.get("typ") == "Kauf"]
        sells = [t for t in txs if t.get("isin") == isin and t.get("typ") == "Verkauf"]
        units_anchor = units_now - sum(t.get("stueck", 0) for t in buys) \
            + sum(t.get("stueck", 0) for t in sells)

        fees += sum(t.get("gebuehr", 0) or 0 for t in buys + sells)
        taxes += sum(t.get("steuern", 0) or 0 for t in sells)

        price_anchor = None
        if units_anchor > 0:
            if isin not in price_cache:
                series = eur_history_dated(isin)
                price_cache[isin] = price_at(series, anchor_date) if series else None
            price_anchor = price_cache[isin]

        cash_in = sum(t.get("gesamt", 0) or 0 for t in sells)
        cash_out = sum(t.get("gesamt", 0) or 0 for t in buys)

        if units_anchor > 0 and price_anchor is None:
            rows.append((name, isin, None, units_anchor, units_now, cash_in, cash_out))
            continue

        value_anchor = (units_anchor * price_anchor) if units_anchor > 0 else 0.0
        contribution = (units_now * price_now - value_anchor) + cash_in - cash_out
        rows.append((name, isin, round(contribution, 2), units_anchor, units_now,
                     cash_in, cash_out))

        for t in sells:
            sell_price = t.get("kurs") or 0
            ref_now = price_now
            if not ref_now:
                if isin not in price_cache:
                    series = eur_history_dated(isin)
                    price_cache[isin] = price_at(series, anchor_date) if series else None
                ref_now, _src = ticker_map.eur_price(isin)
            if sell_price and ref_now and (ref_now - sell_price) / sell_price >= WHIPSAW_MIN_REBOUND:
                whipsaws.append((t.get("datum"), name, t.get("stueck"), sell_price,
                                 round(ref_now, 2),
                                 round((ref_now - sell_price) / sell_price * 100, 1),
                                 t.get("notiz", "")))

    rows.sort(key=lambda r: (r[2] is None, r[2] if r[2] is not None else 0))
    return rows, fees, taxes, whipsaws


def _d(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return datetime.date(1970, 1, 1)


def fmt_rows(rows):
    lines = []
    for name, isin, contrib, u0, u1, cash_in, cash_out in rows:
        c = "  n/a  " if contrib is None else f"{contrib:+8.2f}€"
        extra = ""
        if cash_in or cash_out:
            extra = f"  (Verkäufe {cash_in:.0f}€ / Käufe {cash_out:.0f}€)"
        lines.append(f"  {c}  {name[:38]:40} Stücke {u0}→{u1}{extra}")
    return lines


def main():
    data = load_json(DEPOT, {})
    depot = data.get("depot", {})
    etf = data.get("etf_depot", {})
    bench = depot.get("benchmark", {})
    anker = bench.get("anker", {})

    anchor_arg = None
    for i, a in enumerate(sys.argv):
        if a == "--anchor" and i + 1 < len(sys.argv):
            anchor_arg = sys.argv[i + 1]
    anchor_date = _d(anchor_arg or anker.get("datum"))
    if anchor_date.year == 1970:
        print("Kein Benchmark-Anker gefunden (--anchor YYYY-MM-DD angeben).")
        sys.exit(1)
    today = datetime.date.today()

    price_cache = {}
    a_rows, a_fees, a_taxes, a_whip = attribute_sleeve(depot, anchor_date, today, price_cache)
    e_rows, e_fees, e_taxes, e_whip = attribute_sleeve(etf, anchor_date, today, price_cache)

    rend = bench.get("rendite_pct", {})
    lines = []
    lines.append(f"# Performance-Attribution {anchor_date} → {today}")
    lines.append("")
    lines.append(f"Benchmark seit Anker: Depot {rend.get('depot', '?')}% | "
                 f"DAX {rend.get('dax', '?')}% | MSCI World {rend.get('msci_world', '?')}%")
    lines.append("")
    lines.append("## Aktien-Depot — Beitrag pro Titel (inkl. Trades, netto)")
    lines.extend(fmt_rows(a_rows) or ["  (keine Positionen/Trades im Fenster)"])
    a_sum = sum(r[2] for r in a_rows if r[2] is not None)
    lines.append(f"  Summe: {a_sum:+.2f}€ | Kosten im Fenster: Gebühren {a_fees:.2f}€ + Steuern {a_taxes:.2f}€")
    lines.append("")
    lines.append("## ETF-Sleeve — Beitrag pro Titel")
    lines.extend(fmt_rows(e_rows) or ["  (keine Positionen/Trades im Fenster)"])
    e_sum = sum(r[2] for r in e_rows if r[2] is not None)
    lines.append(f"  Summe: {e_sum:+.2f}€ | Kosten im Fenster: Gebühren {e_fees:.2f}€ + Steuern {e_taxes:.2f}€")
    lines.append("")
    lines.append(f"## Whipsaw-Check (Verkäufe, Kurs seitdem ≥ +{WHIPSAW_MIN_REBOUND*100:.0f}%)")
    for w in a_whip + e_whip:
        lines.append(f"  {w[0]}: {w[2]}x {w[1]} zu {w[3]:.2f}€ verkauft — heute {w[4]:.2f}€ "
                     f"({w[5]:+.1f}%) [{w[6]}]")
    if not (a_whip + e_whip):
        lines.append("  keine — kein Verkauf ist dem Kurs deutlich hinterhergelaufen.")
    lines.append("")
    lines.append("Hinweis: Beitrag = Δ Bestandswert + Verkaufserlöse − Kaufkosten im Fenster; "
                 "Ankerkurse = Schlusskurs am/vor dem Ankertag (Yahoo). "
                 "n/a = kein Ankerkurs auflösbar.")

    report = "\n".join(lines)
    os.makedirs(REPORT_DIR, exist_ok=True)
    out_path = os.path.join(REPORT_DIR, f"{today}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(report)
    print(f"\n-> {out_path}")


if __name__ == "__main__":
    main()
