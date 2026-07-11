import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import (
    DEPOT as depot_path,
    ETF_RANKING as etf_ranking_path,
    ETF_TRADES as recommend_path,
    load_json,
    save_json,
)
import ticker_map

# Autonomer Handel fuer das ETF-Sleeve (eigenes Budget, getrennt vom Aktien-
# Depot). Nutzt das Composite-Ranking aus etf_ranking.py (Momentum/Risiko/
# Sentiment/Struktur, Bucket CORE/SATELLITE/BEOBACHTEN/MEIDEN) statt des
# punktebasierten Aktien-Scorings. Positionen sind pro (sektor, isin) geführt,
# weil derselbe ETF bewusst in mehreren Themen-Sektoren als eigener Slot
# gehalten werden kann (Diversifikations-Basket, siehe etf_katalog.json).
#
# Empfehlungs-Modus (--recommend/--dry-run): schreibt Vorschläge nach
# data/etf_trade_recommendations.json, lässt etf_depot unangetastet.
RECOMMEND = any(a in ("--recommend", "--dry-run") for a in sys.argv[1:])

BUY_BUCKETS = ("CORE", "SATELLITE")     # composite >= 60
SELL_BUCKET = "MEIDEN"                  # composite < 45 (oder AUM-Veto)
ABS_HARD_STOP_PCT = -0.20               # Katastrophenschutz, wie im Aktien-Depot
REBALANCE_MAX_COMPOSITE = 60.0          # nur BEOBACHTEN/MEIDEN dienen als Kapitalquelle

BASE_BUDGET = 100.0
BONUS_PER_POINT = 3.0                   # je Punkt Composite über der Kaufschwelle
MAX_BUDGET = 350.0
MIN_ORDER_VALUE = 40.0
MIN_CASH_RESERVE = 20.0
FEE = 0.0                                # ETF-Sparplan-Modell: gebuehrenfrei
CAP_GAINS_TAX = 0.26375

data = load_json(depot_path, {})
etf_depot = data.get("etf_depot", {})
current_cash = etf_depot.get("aktueller_barbestand", 0.0)
positions = etf_depot.get("positionen", [])
transactions = etf_depot.get("transaktionshistorie", [])
initial_tx_count = len(transactions)

ranking = load_json(etf_ranking_path, {})

# (sektor, isin) -> Ranking-Zeile
ranking_lookup = {}
for sektor, rows in ranking.get("sektoren", {}).items():
    for row in rows:
        isin = row.get("isin")
        if isin:
            ranking_lookup[(sektor, isin)] = row

summary = []


def _today_iso():
    return datetime.now().strftime("%Y-%m-%d")


def reason_for(row):
    if not row:
        return "kein Ranking verfügbar"
    parts = (f"Composite={row.get('composite')} ({row.get('bucket')}) | "
             f"Momentum={row.get('momentum', {}).get('score')} "
             f"Risiko={row.get('risiko', {}).get('score')} "
             f"Sentiment={row.get('sentiment', {}).get('score')} "
             f"Struktur={row.get('struktur', {}).get('score')}")
    warnings = row.get("warnings") or []
    if warnings:
        parts += " | " + ", ".join(warnings)
    return parts


def get_live_price(isin, fallback=None):
    price, _src = ticker_map.eur_price(isin)
    if price:
        return price
    return fallback


def budget_for(composite):
    bonus = max(0.0, composite - 60.0) * BONUS_PER_POINT
    return min(MAX_BUDGET, BASE_BUDGET + bonus)


def _make_sell_record(p, price, notiz, begruendung):
    units = p["stueck"]
    revenue = (units * price) - FEE
    gv_brutto = revenue - p["investiert"]
    steuern = round(gv_brutto * CAP_GAINS_TAX, 2) if gv_brutto > 0 else 0.0
    net_cash = revenue - steuern
    tx = {
        "datum": _today_iso(),
        "typ": "Verkauf",
        "sektor": p.get("sektor"),
        "isin": p.get("isin"),
        "wertpapier": p.get("wertpapier", p.get("isin")),
        "stueck": units,
        "kurs": price,
        "gebuehr": FEE,
        "steuern": steuern,
        "gewinn_verlust": round(gv_brutto, 2),
        "gesamt": round(net_cash, 2),
        "notiz": notiz,
        "begruendung": begruendung,
    }
    return tx, net_cash


def _make_buy_record(sektor, isin, name, units, price, begruendung):
    total_cost = units * price + FEE
    tx = {
        "datum": _today_iso(),
        "typ": "Kauf",
        "sektor": sektor,
        "isin": isin,
        "wertpapier": name,
        "stueck": units,
        "kurs": price,
        "gebuehr": FEE,
        "steuern": 0.0,
        "gewinn_verlust": 0.0,
        "gesamt": round(total_cost, 2),
        "notiz": "Neukauf (ETF-Sleeve)",
        "begruendung": begruendung,
    }
    return tx, total_cost


# ==========================================
# 1. STRATEGISCHER VERKAUF bestehender Positionen
#    Auslöser: Bucket=MEIDEN ODER absoluter Hard-Stop
# ==========================================
positions_to_keep = []
sold_slots = set()  # (sektor, isin) in diesem Lauf verkauft -> kein Rückkauf im selben Lauf

for p in positions:
    isin = p.get("isin")
    sektor = p.get("sektor")
    row = ranking_lookup.get((sektor, isin))
    composite = row.get("composite") if row else None
    bucket = row.get("bucket") if row else None

    current_price = get_live_price(isin, fallback=p.get("boersenkurs", 0))
    kaufkurs = p.get("kaufkurs", 0) or 0
    drawdown = ((current_price - kaufkurs) / kaufkurs) if (kaufkurs and current_price) else 0.0

    sell = False
    sell_reason = ""
    if bucket == SELL_BUCKET:
        sell = True
        sell_reason = f"Bucket={bucket} (Composite={composite})"
    elif drawdown <= ABS_HARD_STOP_PCT:
        sell = True
        sell_reason = f"Absoluter Hard-Stop ({drawdown*100:.1f}% ≤ {ABS_HARD_STOP_PCT*100:.0f}%)"

    if sell:
        begruendung = sell_reason + " | " + reason_for(row)
        tx, net_cash = _make_sell_record(
            p, current_price,
            notiz=f"Strategischer Verkauf ({sell_reason})",
            begruendung=begruendung,
        )
        current_cash += net_cash
        sold_slots.add((sektor, isin))
        summary.append(f"ETF-Verkauf: {p['stueck']}x {p.get('wertpapier')} ({sektor}) zu {current_price:.2f} EUR. {sell_reason}.")
        transactions.append(tx)
    else:
        p["boersenkurs"] = current_price
        p["boersenwert"] = round(p["stueck"] * p["boersenkurs"], 2)
        p["gewinn_verlust"] = round(p["boersenwert"] - p["investiert"], 2)
        if composite is not None:
            p["composite"] = composite
            p["bucket"] = bucket
        positions_to_keep.append(p)

positions = positions_to_keep
held_slots = {(p.get("sektor"), p.get("isin")) for p in positions}

# ==========================================
# 2. KAUF-KANDIDATEN: Bucket CORE/SATELLITE, noch nicht in diesem Slot gehalten
# ==========================================
candidates = []
for (sektor, isin), row in ranking_lookup.items():
    if row.get("bucket") not in BUY_BUCKETS:
        continue
    if (sektor, isin) in held_slots or (sektor, isin) in sold_slots:
        continue
    candidates.append((sektor, isin, row))
candidates.sort(key=lambda x: -x[2].get("composite", 0))

live_prices = {}
target = []
for sektor, isin, row in candidates:
    price = get_live_price(isin)
    if price:
        live_prices[(sektor, isin)] = price
        target.append((sektor, isin, row))

total_needed_cash = sum(budget_for(row.get("composite", 0)) for _, _, row in target)

# ==========================================
# 3. REBALANCING: schwächste Halten-Positionen (Composite < 60) verkaufen,
#    falls Kapital für die Neukäufe fehlt.
# ==========================================
rebalance_candidates = [
    p for p in positions
    if (p.get("sektor"), p.get("isin")) not in {(s, i) for s, i, _ in target}
    and (p.get("composite") is None or p.get("composite") < REBALANCE_MAX_COMPOSITE)
]
rebalance_candidates.sort(key=lambda p: (p.get("composite") if p.get("composite") is not None else 0))

for p in rebalance_candidates:
    if current_cash >= total_needed_cash:
        break
    isin = p.get("isin")
    sektor = p.get("sektor")
    price = p["boersenkurs"]
    begruendung = "Rebalancing | " + reason_for(ranking_lookup.get((sektor, isin)))
    tx, net_cash = _make_sell_record(
        p, price,
        notiz="Rebalancing (Kapitalbeschaffung für Neukäufe)",
        begruendung=begruendung,
    )
    current_cash += net_cash
    summary.append(f"ETF-Rebalancing-Verkauf: {p['stueck']}x {p.get('wertpapier')} ({sektor}) zu {price:.2f} EUR (Composite={p.get('composite')}).")
    transactions.append(tx)
    positions.remove(p)

# ==========================================
# 4. NEUKÄUFE — höchster Composite zuerst, Größe composite-abhängig
# ==========================================
for sektor, isin, row in target:
    price = live_prices.get((sektor, isin))
    if not price:
        continue
    name = row.get("wertpapier", isin)
    budget = budget_for(row.get("composite", 0))
    spendable = current_cash - MIN_CASH_RESERVE
    budget_for_this = min(budget, spendable)
    if budget_for_this < MIN_ORDER_VALUE + FEE:
        continue
    units_to_buy = int((budget_for_this - FEE) / price)
    order_value = units_to_buy * price
    if units_to_buy > 0 and order_value >= MIN_ORDER_VALUE:
        begruendung = reason_for(row)
        tx, total_cost = _make_buy_record(sektor, isin, name, units_to_buy, price, begruendung)
        current_cash -= total_cost
        positions.append({
            "sektor": sektor,
            "wertpapier": name,
            "isin": isin,
            "ticker": row.get("ticker"),
            "stueck": units_to_buy,
            "kaufkurs": price,
            "boersenkurs": price,
            "investiert": round(units_to_buy * price, 2),
            "boersenwert": round(units_to_buy * price, 2),
            "gewinn_verlust": 0.0,
            "composite": row.get("composite"),
            "bucket": row.get("bucket"),
        })
        transactions.append(tx)
        summary.append(f"ETF-Kauf: {units_to_buy}x {name} ({sektor}) zu {price:.2f} EUR, Composite={row.get('composite')}, Budget={budget:.0f}€.")

portfolio_value = sum(p.get("boersenwert", 0) for p in positions)

if RECOMMEND:
    new_trades = transactions[initial_tx_count:]
    recommendation = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "hinweis": ("Regelbasierter Vorschlag (ETF-Ranking: Momentum/Risiko/Sentiment/Struktur). "
                    "Der Agent entscheidet autonom und kann abweichen."),
        "vorgeschlagene_trades": new_trades,
        "zusammenfassung": summary,
        "resultierender_barbestand": round(current_cash, 2),
        "resultierender_portfoliowert": round(portfolio_value, 2),
        "resultierendes_gesamtvermoegen": round(current_cash + portfolio_value, 2),
    }
    save_json(recommend_path, recommendation)
    print(f"[EMPFEHLUNGS-MODUS] {len(new_trades)} ETF-Trade-Vorschläge -> {recommend_path}")
    if summary:
        print("\n".join(summary))
    else:
        print("Vorschlag: keine ETF-Trades nötig, Zielportfolio erreicht.")
else:
    etf_depot["aktueller_barbestand"] = round(current_cash, 2)
    etf_depot["portfoliowert"] = round(portfolio_value, 2)
    etf_depot["gesamtvermoegen"] = round(current_cash + portfolio_value, 2)
    etf_depot["positionen"] = positions
    etf_depot["transaktionshistorie"] = transactions
    data["etf_depot"] = etf_depot

    save_json(depot_path, data)

    if summary:
        print("\n".join(summary))
    else:
        print("Keine ETF-Transaktionen notwendig. Zielportfolio ist erreicht.")
