"""Autonomer Handel fuer das ETF-Sleeve (eigenes Budget, getrennt vom Aktien-
Depot). Nutzt das Composite-Ranking aus etf_ranking.py (Momentum/Risiko/
Sentiment/Struktur, Bucket CORE/SATELLITE/BEOBACHTEN/MEIDEN) statt des
punktebasierten Aktien-Scorings. Positionen sind pro (sektor, isin) geführt,
weil derselbe ETF bewusst in mehreren Themen-Sektoren als eigener Slot
gehalten werden kann (Diversifikations-Basket, siehe etf_katalog.json).

Empfehlungs-Modus (--recommend/--dry-run): schreibt Vorschläge nach
data/etf_trade_recommendations.json, lässt etf_depot unangetastet.

Struktur wie update_depot.py: Konstanten + reine Helfer oben, Handelsphasen als
eigene Funktionen auf einem RunState, orchestriert von main(). Datei-/Netz-
Zugriffe passieren NICHT beim Import, sondern erst in main() — dadurch ist die
Phasenlogik mit Fixture-Daten testbar (tests/test_update_etf_depot.py).
"""

import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
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

BUY_BUCKETS = ("CORE", "SATELLITE")     # composite >= 60
SELL_BUCKET = "MEIDEN"                  # composite < 45 (oder AUM-Veto)
ABS_HARD_STOP_PCT = -0.20               # Katastrophenschutz, wie im Aktien-Depot
REBALANCE_MAX_COMPOSITE = 60.0          # nur BEOBACHTEN/MEIDEN dienen als Kapitalquelle

# --- Konviktions-Schwellen fuer Kapitaleinsatz ----------------------------
# Neuzugaenge nur mit echter Konviktion, nicht bloss "weil noch nicht gehalten".
# Verhindert, dass Idle-Cash in schwache 60er-SATELLITEs fliesst, obwohl die
# starken ETFs bereits gehalten werden (siehe Clean-Energy-Fehlkauf 2026-07-23).
NEW_BUY_MIN_COMPOSITE = 70.0            # Neukauf eines NEUEN ISIN erst ab Composite >= 70
TOPUP_MIN_COMPOSITE = 75.0             # Idle-Cash stockt nur starke CORE-Bestaende auf, sonst Cash halten

# --- Sanfter Exit (zusaetzlich zum -20% Hard-Stop) -------------------------
# Schneidet schwache/abrutschende Positionen frueher, statt sie bis MEIDEN
# oder -20% laufen zu lassen (grosse Totzone im alten Modell).
SOFT_STOP_BUCKET = "BEOBACHTEN"         # Composite 45-59: Ranking kippt
SOFT_STOP_LOSS_PCT = -0.03              # ... + Position im Minus -> Verkauf
TRAIL_STOP_PCT = -0.12                  # Trailing-Stop: -12% vom Positionshoch
TRAIL_EXEMPT_COMPOSITE = 75.0           # CORE (>=75) bleibt vom Trailing-Stop verschont

# --- Sektor-Cap (Parität zum Aktien-Motor, Phase Sektor-Abbau) -------------
SECTOR_CAP = 0.30                       # kein Themen-Sektor > 30% des ETF-Sleeves

BASE_BUDGET = 210.0                     # >= MIN_ORDER, damit Neukaeufe die Fragmentierungs-Schwelle raeumen
BONUS_PER_POINT = 3.0                   # je Punkt Composite über der Kaufschwelle
MAX_BUDGET = 350.0
MIN_ORDER_VALUE = 200.0                 # war 120/40: verhindert Mini-Positionen (De-Fragmentierung)
# Mindest-Positionsgroesse im Bestand: Positionen unter dieser Schwelle sind
# Rauschen ohne Renditebeitrag (2026-07-23: 17 Positionen, 8 davon < 200€,
# kleinste 53€ — trotz frueherer De-Frag-Fixes). Schwache Minis (< TOPUP_MIN_
# COMPOSITE) werden verkauft und das Kapital fliesst ueber Top-up in starke
# CORE-Bestaende; starke Minis bleiben und werden vom Top-up aufgestockt.
MIN_POSITION_VALUE = 150.0
MIN_CASH_RESERVE = 20.0
FEE = 0.0                                # ETF-Sparplan-Modell: gebuehrenfrei
CAP_GAINS_TAX = 0.26375


@dataclass
class EtfRunState:
    """Veränderlicher Zustand eines ETF-Engine-Laufs."""
    current_cash: float
    positions: list
    transactions: list
    initial_tx_count: int
    ranking_lookup: dict
    summary: list = field(default_factory=list)
    live_prices: dict = field(default_factory=dict)
    sold_slots: set = field(default_factory=set)  # (sektor, isin) verkauft -> kein Rückkauf
    target: list = field(default_factory=list)    # [(sektor, isin, row), ...]


def consolidate_by_isin(positions, summary):
    """De-Fragmentierung: derselbe ETF wurde bisher pro (sektor, isin) als
    eigener Slot gehalten -> derselbe Fonds lag mehrfach in Mini-Lots. Wir
    fuehren gleiche ISINs zu EINER Position zusammen (Stueck + Einstand
    summiert, gewichteter Kaufkurs). Sektor-Label = Slot mit groesstem
    Investitionsvolumen. Idempotent: ohne Duplikate unveraendert."""
    merged = {}
    order = []
    for p in positions:
        isin = p.get("isin")
        if isin not in merged:
            merged[isin] = dict(p)
            order.append(isin)
            continue
        q = merged[isin]
        # groesserer Slot bestimmt das Sektor-Label
        if p.get("investiert", 0) > q.get("investiert", 0):
            q["sektor"] = p.get("sektor")
            q["wertpapier"] = p.get("wertpapier", q.get("wertpapier"))
        q["stueck"] = round(q.get("stueck", 0) + p.get("stueck", 0), 6)
        q["investiert"] = round(q.get("investiert", 0) + p.get("investiert", 0), 2)
        if q["stueck"]:
            q["kaufkurs"] = round(q["investiert"] / q["stueck"], 4)
        # Positionshoch (fuer Trailing-Stop) konservativ uebernehmen
        q["peak_kurs"] = max(q.get("peak_kurs", 0) or 0, p.get("peak_kurs", 0) or 0)
    result = [merged[i] for i in order]
    n_removed = len(positions) - len(result)
    if n_removed > 0:
        summary.append(f"De-Fragmentierung: {n_removed} Duplikat-Slot(s) zu ISIN-Positionen zusammengefuehrt.")
    return result


def build_ranking_lookup(ranking):
    """(sektor, isin) -> Ranking-Zeile."""
    lookup = {}
    for sektor, rows in ranking.get("sektoren", {}).items():
        for row in rows:
            isin = row.get("isin")
            if isin:
                lookup[(sektor, isin)] = row
    return lookup


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


def _make_sell_record(p, price, notiz, begruendung, units=None):
    stueck = p["stueck"]
    units = stueck if units is None else min(units, stueck)
    invest_share = (p["investiert"] * units / stueck) if stueck else p["investiert"]
    revenue = (units * price) - FEE
    gv_brutto = revenue - invest_share
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
#    Auslöser: Bucket=MEIDEN ODER absoluter Hard-Stop ODER Soft-/Trailing-Stop
# ==========================================

def phase_strategic_sell(state):
    positions_to_keep = []
    for p in state.positions:
        isin = p.get("isin")
        sektor = p.get("sektor")
        row = state.ranking_lookup.get((sektor, isin))
        composite = row.get("composite") if row else None
        bucket = row.get("bucket") if row else None

        current_price = get_live_price(isin, fallback=p.get("boersenkurs", 0))
        kaufkurs = p.get("kaufkurs", 0) or 0
        drawdown = ((current_price - kaufkurs) / kaufkurs) if (kaufkurs and current_price) else 0.0

        # Positionshoch fuer den Trailing-Stop pflegen
        peak = max(p.get("peak_kurs", 0) or 0, kaufkurs, current_price)
        trail = ((current_price - peak) / peak) if peak else 0.0

        sell = False
        sell_reason = ""
        if bucket == SELL_BUCKET:
            sell = True
            sell_reason = f"Bucket={bucket} (Composite={composite})"
        elif drawdown <= ABS_HARD_STOP_PCT:
            sell = True
            sell_reason = f"Absoluter Hard-Stop ({drawdown*100:.1f}% ≤ {ABS_HARD_STOP_PCT*100:.0f}%)"
        elif bucket == SOFT_STOP_BUCKET and drawdown <= SOFT_STOP_LOSS_PCT:
            sell = True
            sell_reason = (f"Soft-Stop (Bucket={bucket}, Composite={composite}, "
                           f"{drawdown*100:.1f}% ≤ {SOFT_STOP_LOSS_PCT*100:.0f}%)")
        elif (composite is not None and composite < TRAIL_EXEMPT_COMPOSITE
              and trail <= TRAIL_STOP_PCT):
            sell = True
            sell_reason = (f"Trailing-Stop ({trail*100:.1f}% vom Hoch {peak:.2f} ≤ "
                           f"{TRAIL_STOP_PCT*100:.0f}%)")

        if sell:
            begruendung = sell_reason + " | " + reason_for(row)
            tx, net_cash = _make_sell_record(
                p, current_price,
                notiz=f"Strategischer Verkauf ({sell_reason})",
                begruendung=begruendung,
            )
            state.current_cash += net_cash
            state.sold_slots.add((sektor, isin))
            state.summary.append(f"ETF-Verkauf: {p['stueck']}x {p.get('wertpapier')} ({sektor}) zu {current_price:.2f} EUR. {sell_reason}.")
            state.transactions.append(tx)
        else:
            p["boersenkurs"] = current_price
            p["boersenwert"] = round(p["stueck"] * p["boersenkurs"], 2)
            p["gewinn_verlust"] = round(p["boersenwert"] - p["investiert"], 2)
            p["peak_kurs"] = round(peak, 4)
            if composite is not None:
                p["composite"] = composite
                p["bucket"] = bucket
            positions_to_keep.append(p)

    state.positions = positions_to_keep


# ==========================================
# 1b. SEKTOR-ABBAU: kein Themen-Sektor > SECTOR_CAP des Sleeves.
#     Parität zum Aktien-Motor: schwaechste Position (Composite) des
#     ueberlaufenden Sektors zuerst verkaufen, bis die Quote wieder passt.
# ==========================================

def _sector_over_cap(positions):
    total = sum(p.get("boersenwert", 0) for p in positions)
    if total <= 0:
        return None, 0.0, total
    weights = defaultdict(float)
    for p in positions:
        weights[p.get("sektor")] += p.get("boersenwert", 0)
    sektor, weight = max(weights.items(), key=lambda kv: kv[1])
    return (sektor if weight / total > SECTOR_CAP else None), weight / total, total


def phase_sector_reduction(state):
    while True:
        over_sektor, quote, tot = _sector_over_cap(state.positions)
        if not over_sektor:
            break
        in_sektor = [p for p in state.positions if p.get("sektor") == over_sektor]
        if len(in_sektor) <= 1:
            break  # Einzelposition laesst sich nicht durch Teilverkauf reduzieren
        weakest = min(in_sektor, key=lambda p: (p.get("composite") if p.get("composite") is not None else 0))
        price = weakest.get("boersenkurs", 0)
        # Nur so viele Stücke verkaufen, wie nötig, um den Sektor knapp unter den
        # Cap zu bringen — kein Komplettverkauf mit anschließendem Rückkauf.
        sektor_value = sum(p.get("boersenwert", 0) for p in in_sektor)
        if price > 0 and (1 - SECTOR_CAP) > 0:
            need = (sektor_value - SECTOR_CAP * tot) / (price * (1 - SECTOR_CAP))
            units_to_sell = max(1, math.ceil(need))
        else:
            units_to_sell = weakest["stueck"]
        units_to_sell = min(units_to_sell, weakest["stueck"])
        tx, net_cash = _make_sell_record(
            weakest, price,
            notiz=f"Sektor-Abbau ({over_sektor} {quote*100:.0f}% > {SECTOR_CAP*100:.0f}%)",
            begruendung=f"Sektor-Cap: {over_sektor} bei {quote*100:.1f}% | " + reason_for(state.ranking_lookup.get((over_sektor, weakest.get('isin')))),
            units=units_to_sell,
        )
        state.current_cash += net_cash
        state.summary.append(f"ETF-Sektor-Abbau: {units_to_sell}x {weakest.get('wertpapier')} ({over_sektor}) zu {price:.2f} EUR — Sektor {quote*100:.0f}% > {SECTOR_CAP*100:.0f}%.")
        state.transactions.append(tx)
        # Gleiche ISIN im selben Lauf nicht wieder kaufen (verhindert Verkauf+Rückkauf).
        state.sold_slots.add((weakest.get("sektor"), weakest.get("isin")))
        if units_to_sell >= weakest["stueck"]:
            state.positions.remove(weakest)
        else:
            remaining = weakest["stueck"] - units_to_sell
            weakest["investiert"] = round(weakest["investiert"] * remaining / weakest["stueck"], 2)
            weakest["stueck"] = remaining
            weakest["boersenwert"] = round(remaining * price, 2)
            weakest["gewinn_verlust"] = round(weakest["boersenwert"] - weakest["investiert"], 2)
            break  # nach Teilverkauf ist der Sektor unter dem Cap


# ==========================================
# 1c. MINI-KONSOLIDIERUNG: Positionen unter MIN_POSITION_VALUE ohne
#     Top-up-Perspektive (Composite < TOPUP_MIN_COMPOSITE) verkaufen.
#     Das Kapital wandert ueber die Top-up-Phase in starke CORE-Bestaende
#     statt als Streubesitz liegen zu bleiben.
# ==========================================

def phase_mini_consolidation(state):
    for p in list(state.positions):
        wert = p.get("boersenwert", 0) or 0
        composite = p.get("composite")
        if wert <= 0 or wert >= MIN_POSITION_VALUE:
            continue
        if composite is not None and composite >= TOPUP_MIN_COMPOSITE:
            continue  # starker Mini: bleibt und wird vom Top-up aufgestockt
        sektor = p.get("sektor")
        isin = p.get("isin")
        price = p.get("boersenkurs", 0)
        if not price:
            continue
        grund = (f"Mini-Konsolidierung: {wert:.2f}€ < {MIN_POSITION_VALUE:.0f}€ "
                 f"Mindestgroesse (Composite={composite})")
        tx, net_cash = _make_sell_record(
            p, price,
            notiz="Mini-Konsolidierung (Position unter Mindestgroesse)",
            begruendung=grund + " | " + reason_for(state.ranking_lookup.get((sektor, isin))),
        )
        state.current_cash += net_cash
        state.sold_slots.add((sektor, isin))
        state.summary.append(f"ETF-Mini-Konsolidierung: {p['stueck']}x {p.get('wertpapier')} "
                             f"({sektor}) zu {price:.2f} EUR verkauft — {wert:.2f}€ unter "
                             f"Mindestgroesse {MIN_POSITION_VALUE:.0f}€.")
        state.transactions.append(tx)
        state.positions.remove(p)


# ==========================================
# 2. KAUF-KANDIDATEN: Bucket CORE/SATELLITE, noch nicht in diesem Slot gehalten
# ==========================================

def phase_plan(state):
    held_isins = {p.get("isin") for p in state.positions}
    sold_isins = {isin for (_s, isin) in state.sold_slots}

    # Pro ISIN nur EIN Kaufkandidat (bester Sektor-Slot), damit derselbe ETF
    # nicht erneut in mehreren Themen-Sektoren aufgebaut wird (De-Fragmentierung).
    best_by_isin = {}
    for (sektor, isin), row in state.ranking_lookup.items():
        if row.get("bucket") not in BUY_BUCKETS:
            continue
        if isin in held_isins or isin in sold_isins:
            continue
        # Konviktions-Floor: einen NEUEN ETF nur bei echter Staerke aufnehmen.
        if (row.get("composite") or 0) < NEW_BUY_MIN_COMPOSITE:
            continue
        cur = best_by_isin.get(isin)
        if cur is None or row.get("composite", 0) > cur[2].get("composite", 0):
            best_by_isin[isin] = (sektor, isin, row)
    candidates = list(best_by_isin.values())
    candidates.sort(key=lambda x: -x[2].get("composite", 0))

    state.target = []
    for sektor, isin, row in candidates:
        price = get_live_price(isin)
        if price:
            state.live_prices[(sektor, isin)] = price
            state.target.append((sektor, isin, row))

    return sum(budget_for(row.get("composite", 0)) for _, _, row in state.target)


# ==========================================
# 3. REBALANCING: schwächste Halten-Positionen (Composite < 60) verkaufen,
#    falls Kapital für die Neukäufe fehlt.
# ==========================================

def phase_rebalance(state, total_needed_cash):
    target_slots = {(s, i) for s, i, _ in state.target}
    rebalance_candidates = [
        p for p in state.positions
        if (p.get("sektor"), p.get("isin")) not in target_slots
        and (p.get("composite") is None or p.get("composite") < REBALANCE_MAX_COMPOSITE)
    ]
    rebalance_candidates.sort(key=lambda p: (p.get("composite") if p.get("composite") is not None else 0))

    for p in rebalance_candidates:
        if state.current_cash >= total_needed_cash:
            break
        isin = p.get("isin")
        sektor = p.get("sektor")
        price = p["boersenkurs"]
        begruendung = "Rebalancing | " + reason_for(state.ranking_lookup.get((sektor, isin)))
        tx, net_cash = _make_sell_record(
            p, price,
            notiz="Rebalancing (Kapitalbeschaffung für Neukäufe)",
            begruendung=begruendung,
        )
        state.current_cash += net_cash
        state.summary.append(f"ETF-Rebalancing-Verkauf: {p['stueck']}x {p.get('wertpapier')} ({sektor}) zu {price:.2f} EUR (Composite={p.get('composite')}).")
        state.transactions.append(tx)
        state.positions.remove(p)


# ==========================================
# 4. NEUKÄUFE — höchster Composite zuerst, Größe composite-abhängig
# ==========================================

def phase_buy(state):
    for sektor, isin, row in state.target:
        price = state.live_prices.get((sektor, isin))
        if not price:
            continue
        name = row.get("wertpapier", isin)
        budget = budget_for(row.get("composite", 0))
        spendable = state.current_cash - MIN_CASH_RESERVE
        budget_for_this = min(budget, spendable)
        if budget_for_this < MIN_ORDER_VALUE + FEE:
            continue
        units_to_buy = int((budget_for_this - FEE) / price)
        order_value = units_to_buy * price
        # Sektor-Cap auf der Kaufseite: keinen Sektor ueber SECTOR_CAP treiben
        held_value = sum(p.get("boersenwert", 0) for p in state.positions)
        sektor_value = sum(p.get("boersenwert", 0) for p in state.positions if p.get("sektor") == sektor)
        proj_total = held_value + order_value
        if proj_total > 0 and (sektor_value + order_value) / proj_total > SECTOR_CAP:
            state.summary.append(f"ETF-Kauf uebersprungen: {name} ({sektor}) — Sektor-Cap {SECTOR_CAP*100:.0f}% erreicht.")
            continue
        if units_to_buy > 0 and order_value >= MIN_ORDER_VALUE:
            begruendung = reason_for(row)
            tx, total_cost = _make_buy_record(sektor, isin, name, units_to_buy, price, begruendung)
            state.current_cash -= total_cost
            state.positions.append({
                "sektor": sektor,
                "wertpapier": name,
                "isin": isin,
                "ticker": row.get("ticker"),
                "stueck": units_to_buy,
                "kaufkurs": price,
                "boersenkurs": price,
                "peak_kurs": price,
                "investiert": round(units_to_buy * price, 2),
                "boersenwert": round(units_to_buy * price, 2),
                "gewinn_verlust": 0.0,
                "composite": row.get("composite"),
                "bucket": row.get("bucket"),
            })
            state.transactions.append(tx)
            state.summary.append(f"ETF-Kauf: {units_to_buy}x {name} ({sektor}) zu {price:.2f} EUR, Composite={row.get('composite')}, Budget={budget:.0f}€.")


# ==========================================
# 5. TOP-UP: verbleibendes Idle-Cash in die staerksten CORE-Bestaende
#    (Composite >= TOPUP_MIN_COMPOSITE) aufstocken, statt in schwache
#    Neuzugaenge. Kein Kandidat / Cash zu klein -> Cash bleibt liegen.
# ==========================================

def phase_topup(state):
    topup_candidates = [
        p for p in state.positions
        if (p.get("composite") is not None and p.get("composite") >= TOPUP_MIN_COMPOSITE)
        and (p.get("sektor"), p.get("isin")) not in state.sold_slots
    ]
    topup_candidates.sort(key=lambda p: -(p.get("composite") or 0))

    for p in topup_candidates:
        spendable = state.current_cash - MIN_CASH_RESERVE
        if spendable < MIN_ORDER_VALUE + FEE:
            break
        sektor = p.get("sektor")
        isin = p.get("isin")
        price = get_live_price(isin, p.get("boersenkurs"))
        if not price:
            continue
        budget_for_this = min(budget_for(p.get("composite", 0)), spendable)
        units_to_buy = int((budget_for_this - FEE) / price)
        order_value = units_to_buy * price
        if units_to_buy <= 0 or order_value < MIN_ORDER_VALUE:
            continue
        # Sektor-Cap auch beim Aufstocken einhalten.
        held_value = sum(q.get("boersenwert", 0) for q in state.positions)
        sektor_value = sum(q.get("boersenwert", 0) for q in state.positions if q.get("sektor") == sektor)
        proj_total = held_value + order_value
        if proj_total > 0 and (sektor_value + order_value) / proj_total > SECTOR_CAP:
            state.summary.append(f"ETF-Top-up uebersprungen: {p.get('wertpapier')} ({sektor}) — Sektor-Cap {SECTOR_CAP*100:.0f}% erreicht.")
            continue
        begruendung = "Top-up starker CORE-Bestand | " + reason_for(state.ranking_lookup.get((sektor, isin)))
        tx, total_cost = _make_buy_record(sektor, isin, p.get("wertpapier", isin), units_to_buy, price, begruendung)
        tx["notiz"] = "Top-up (ETF-Sleeve)"
        state.current_cash -= total_cost
        # Bestehende Position aufstocken (gewichteter Einstand).
        new_units = round(p["stueck"] + units_to_buy, 6)
        p["investiert"] = round(p.get("investiert", 0) + order_value, 2)
        p["stueck"] = new_units
        p["kaufkurs"] = round(p["investiert"] / new_units, 4) if new_units else price
        p["boersenkurs"] = price
        p["boersenwert"] = round(new_units * price, 2)
        p["gewinn_verlust"] = round(p["boersenwert"] - p["investiert"], 2)
        p["peak_kurs"] = max(p.get("peak_kurs", 0) or 0, price)
        state.transactions.append(tx)
        state.summary.append(f"ETF-Top-up: {units_to_buy}x {p.get('wertpapier')} ({sektor}) zu {price:.2f} EUR, Composite={p.get('composite')} (CORE-Aufstockung).")


# ==========================================
# AUSGABE + ORCHESTRIERUNG
# ==========================================

def write_recommendation(state, portfolio_value):
    new_trades = state.transactions[state.initial_tx_count:]
    recommendation = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "hinweis": ("Regelbasierter Vorschlag (ETF-Ranking: Momentum/Risiko/Sentiment/Struktur). "
                    "Der Agent entscheidet autonom und kann abweichen."),
        "vorgeschlagene_trades": new_trades,
        "zusammenfassung": state.summary,
        "resultierender_barbestand": round(state.current_cash, 2),
        "resultierender_portfoliowert": round(portfolio_value, 2),
        "resultierendes_gesamtvermoegen": round(state.current_cash + portfolio_value, 2),
    }
    save_json(recommend_path, recommendation)
    print(f"[EMPFEHLUNGS-MODUS] {len(new_trades)} ETF-Trade-Vorschläge -> {recommend_path}")
    if state.summary:
        print("\n".join(state.summary))
    else:
        print("Vorschlag: keine ETF-Trades nötig, Zielportfolio erreicht.")


def write_depot(data, etf_depot, state, portfolio_value):
    etf_depot["aktueller_barbestand"] = round(state.current_cash, 2)
    etf_depot["portfoliowert"] = round(portfolio_value, 2)
    etf_depot["gesamtvermoegen"] = round(state.current_cash + portfolio_value, 2)
    etf_depot["positionen"] = state.positions
    etf_depot["transaktionshistorie"] = state.transactions
    data["etf_depot"] = etf_depot

    save_json(depot_path, data)

    if state.summary:
        print("\n".join(state.summary))
    else:
        print("Keine ETF-Transaktionen notwendig. Zielportfolio ist erreicht.")


def main(recommend=False):
    data = load_json(depot_path, {})
    etf_depot = data.get("etf_depot", {})
    transactions = etf_depot.get("transaktionshistorie", [])
    state = EtfRunState(
        current_cash=etf_depot.get("aktueller_barbestand", 0.0),
        positions=etf_depot.get("positionen", []),
        transactions=transactions,
        initial_tx_count=len(transactions),
        ranking_lookup=build_ranking_lookup(load_json(etf_ranking_path, {})),
    )
    state.positions = consolidate_by_isin(state.positions, state.summary)

    phase_strategic_sell(state)
    phase_sector_reduction(state)
    phase_mini_consolidation(state)
    total_needed_cash = phase_plan(state)
    phase_rebalance(state, total_needed_cash)
    phase_buy(state)
    phase_topup(state)

    portfolio_value = sum(p.get("boersenwert", 0) for p in state.positions)

    if recommend:
        write_recommendation(state, portfolio_value)
    else:
        write_depot(data, etf_depot, state, portfolio_value)


if __name__ == "__main__":
    recommend = any(a in ("--recommend", "--dry-run") for a in sys.argv[1:])
    main(recommend=recommend)
