import os
import sys
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import DEPOT as depot_path, CHART, FUNDA, SENT as sentiment_path, TRADES as recommend_path, load_json, save_json
from consistency import data_consistency

# Empfehlungs-Modus: berechnet Score/Sentiment/Veto und die Trades, die das
# regelbasierte System vorschlagen WÜRDE, schreibt sie nach
# data/trade_recommendations.json und lässt depot_status.json unangetastet.
# So bleibt die finale Kauf-/Verkaufsentscheidung beim autonomen Agenten.
RECOMMEND = any(a in ("--recommend", "--dry-run") for a in sys.argv[1:])

data = load_json(depot_path, {})
depot = data.get("depot", {})
current_cash = depot.get("aktueller_barbestand", 10000.0)
positions = depot.get("positionen", [])
transactions = depot.get("transaktionshistorie", [])
initial_tx_count = len(transactions)  # neue Trades dieses Laufs = ab hier

chart_data = load_json(CHART, {})
funda_data = load_json(FUNDA, {})

# KI-Sentiment (Stufe 1 + 2), vom Portfoliomanager-Agent erzeugt.
# Optional: fehlt die Datei, läuft alles rein deterministisch weiter.
# Vertrag (siehe docs/SENTIMENT_STAGE.md):
#   { "generated_at": "...",
#     "scores": { "<ISIN>": {"sentiment_score": int(-3..3), "veto": bool,
#                            "confidence": float(0..1), "event_kategorie": str,
#                            "begruendung": str} } }
# confidence/event_kategorie sind optional mit Default — ältere Dateien ohne
# diese Felder rechnen unverändert weiter (Default-Confidence 0.7 = weder
# gedämpft noch verstärkt, entspricht dem alten Verhalten näherungsweise).
sentiment_data = load_json(sentiment_path, {"scores": {}})

SENTIMENT_MIN, SENTIMENT_MAX = -3, 3
DEFAULT_CONFIDENCE = 0.7
REVIEW_FLAG_THRESHOLD = -2  # rohes Sentiment auf Bestand ab hier -> review_flag

def get_sentiment(isin):
    """Returns (score, veto, begruendung, confidence, event_kategorie) — geklemmt und defensiv."""
    entry = sentiment_data.get("scores", {}).get(isin)
    if not entry:
        return 0, False, "", DEFAULT_CONFIDENCE, "Keine"
    try:
        s = int(round(float(entry.get("sentiment_score", 0))))
    except (TypeError, ValueError):
        s = 0
    s = max(SENTIMENT_MIN, min(SENTIMENT_MAX, s))
    try:
        conf = float(entry.get("confidence", DEFAULT_CONFIDENCE))
    except (TypeError, ValueError):
        conf = DEFAULT_CONFIDENCE
    conf = max(0.0, min(1.0, conf))
    kategorie = entry.get("event_kategorie") or "Sonstiges"
    return s, bool(entry.get("veto", False)), entry.get("begruendung", ""), conf, kategorie

# ==========================================
# SCORING-SYSTEM
# ==========================================

# Kauf-Schwelle: ADAPTIV. Fixer Floor = BUY_FLOOR, effektive Schwelle ist
# max(BUY_FLOOR, 80er-Perzentil aller aktiven Kandidatenscores). Das hebt
# die Latte in starken Märkten automatisch (mehr Auswahl → wähle die besten),
# ohne in schwachen Märkten alle Käufe zu blockieren.
BUY_FLOOR = 6
BUY_PERCENTILE = 0.80       # nur die Top-20% werden Kauf-Kandidaten
# Fallback wenn Kandidatenmenge zu klein für sinnvolles Perzentil ist.
BUY_FALLBACK_THRESHOLD = 8
BUY_MIN_CANDIDATES = 10     # unter dieser Anzahl greift der Fallback
# Score below this triggers Verkauf für bestehende Positionen
SELL_THRESHOLD = 4
# Rebalancing-Schwelle: nur Halten-Positionen unter diesem festen Wert werden
# zur Kapitalbeschaffung verkauft. Absichtlich NICHT die adaptive Kaufschwelle —
# sonst würden in starken Märkten (adaptive Schwelle hoch) alle "guten aber
# nicht Top-Kandidaten" abgeräumt.
REBALANCE_THRESHOLD = 8
# Watch-Modus: neu aufgenommene Papiere (Opportunity-Scan) haben oft noch
# keine belastbare Chart-Historie (SMA200/RSI/MACD). Sie werden NICHT gekauft,
# bleiben aber im Universum stehen, bis genug Daten da sind.
WATCH_MIN_CLOSES = 200          # SMA200 braucht 200 Tage
WATCH_MARKERS = ("watch-kandidat", "opportunity-scan")
# Zweistufiger Stop-Loss (marktbereinigt):
#  1) ABSOLUTER HARD-STOP: fällt eine Position absolut um mehr als X unter den
#     Kaufkurs, wird IMMER verkauft — Katastrophenschutz, auch wenn der ganze
#     Markt fällt. Der Hauptjob des Stops bleibt Kapitalschutz.
#  2) RELATIVER STOP: greift nur, wenn die Position im Minus ist UND ihre
#     beta-bereinigte Underperformance ggü. dem DAX (Alpha) unter -REL_STOP_PCT
#     liegt. So wird man bei breiten Marktdips NICHT rausgekegelt, aber echte
#     unternehmensspezifische Schwäche früher erkannt.
ABS_HARD_STOP_PCT = -0.20   # absoluter Notausgang (Katastrophenschutz)
REL_STOP_PCT = -0.12        # beta-bereinigte Underperformance vs. DAX
# Cash-Management: Mindest-Barreserve nie unterschreiten, und keine Mini-Käufe
# (Gebühren-Drag). Bei 5 € Gebühr wären 100 € Order = 5 % Reibung.
MIN_CASH_RESERVE = 25.0
MIN_ORDER_VALUE = 100.0
# Klumpenrisiko-Hardcap: risk_report.py WARNT schon ab 30% Sektoranteil, aber
# blockiert nichts. Hier greift die Kaufsperre erst später (60%) und kappt/
# blockiert NEUE Käufe, die einen Sektor darüber treiben würden — bestehende
# Positionen werden dadurch nicht verkauft, das ist reines Wachstums-Limit.
MAX_SEKTOR_PCT_HARD = 0.60

def get_chart_item(isin):
    if not isin: return None
    for sector, items in chart_data.get("sektoren", {}).items():
        for item in items:
            if item.get("isin") == isin:
                return item
    return None

def get_funda_item(isin):
    if not isin: return None
    for sector, items in funda_data.get("sektoren", {}).items():
        for item in items:
            if item.get("isin") == isin:
                return item
    return None

def compute_chart_score(isin):
    """Chart-Score aus technischen Indikatoren (max ~12, min ~-11)."""
    item = get_chart_item(isin)
    if not item:
        return 0, []
    score = 0
    details = []

    emp = (item.get("empfehlung") or "").lower()
    if "kaufen" in emp:
        score += 3; details.append("Empf.+3")
    elif "verkauf" in emp:
        score -= 5; details.append("Empf.-5")

    trend = (item.get("trend") or "").lower()
    if "aufwärts" in trend and "leicht" not in trend:
        score += 2; details.append("Trend+2")
    elif "leicht" in trend and "aufwärts" in trend:
        score += 1; details.append("Trend+1")
    elif "leicht" in trend and "abwärts" in trend:
        score -= 1; details.append("Trend-1")
    elif "abwärts" in trend:
        score -= 3; details.append("Trend-3")

    rsi = item.get("rsi_14")
    if rsi is not None:
        if rsi < 30:
            score += 3; details.append(f"RSI+3({rsi:.0f})")
        elif rsi < 50:
            score += 2; details.append(f"RSI+2({rsi:.0f})")
        elif rsi < 65:
            score += 1; details.append(f"RSI+1({rsi:.0f})")
        elif rsi > 75:
            score -= 2; details.append(f"RSI-2({rsi:.0f})")

    macd = item.get("macd", "")
    if macd == "Positiv":
        score += 2; details.append("MACD+2")
    elif macd == "Neutral":
        score += 1; details.append("MACD+1")
    elif macd == "Negativ":
        score -= 1; details.append("MACD-1")

    kurs = item.get("aktueller_kurs") or 0
    sma50 = item.get("sma_50") or 0
    sma200 = item.get("sma_200") or 0
    if kurs > 0 and sma50 > 0 and kurs > sma50:
        score += 1; details.append("SMA50+1")
    if kurs > 0 and sma200 > 0 and kurs > sma200:
        score += 1; details.append("SMA200+1")

    return score, details

# Marker-Texte, die eine Fundamental-Analyse als Platzhalter (keine echten
# Kennzahlen) ausweisen — solche Einträge dürfen den Score nicht aufblähen.
_FUNDA_PLACEHOLDER_MARKERS = ("vervollständigung", "ergänzt zur", "platzhalter")


def is_funda_placeholder(item):
    b = (item.get("begruendung") or "").lower()
    return any(m in b for m in _FUNDA_PLACEHOLDER_MARKERS)


def compute_funda_score(isin):
    """Fundamental-Score (max ~9, min ~-7)."""
    item = get_funda_item(isin)
    if not item:
        return 0, []
    # Platzhalter-Fundamentaldaten neutral werten (keine erfundenen Kennzahlen
    # ins Scoring einfließen lassen).
    if is_funda_placeholder(item):
        return 0, ["Funda=Platzhalter→0"]
    score = 0
    details = []

    emp = (item.get("empfehlung") or "").lower()
    if emp and emp != "n/a":
        if "kaufen" in emp:
            score += 3; details.append("Empf.+3")
        elif "verkauf" in emp:
            score -= 5; details.append("Empf.-5")

    bew = (item.get("bewertung") or "").lower()
    if "attraktiv" in bew:
        score += 2; details.append("Bew.+2")
    elif "neutral" in bew:
        score += 1; details.append("Bew.+1")
    elif "unattraktiv" in bew:
        score -= 1; details.append("Bew.-1")

    risiko = (item.get("risiko") or "").lower()
    if "niedrig" in risiko:
        score += 2; details.append("Risiko+2")
    elif "mittel" in risiko:
        score += 1; details.append("Risiko+1")
    elif "hoch" in risiko:
        score -= 1; details.append("Risiko-1")

    gw = item.get("gewinnwachstum_yoy")
    if gw is not None:
        if gw > 20:
            score += 2; details.append(f"GW+2({gw:.0f}%)")
        elif gw > 5:
            score += 1; details.append(f"GW+1({gw:.0f}%)")
        elif gw < 0:
            score -= 1; details.append(f"GW-1({gw:.0f}%)")

    return score, details

def total_score(isin):
    cs, cd = compute_chart_score(isin)
    fs, fd = compute_funda_score(isin)
    ss, _, _, confidence, _ = get_sentiment(isin)
    # Confidence dämpft das Gewicht: ein schwach belegtes Urteil (wenige/vage
    # Schlagzeilen) wirkt schwächer auf den Score als ein gut belegtes.
    ss_weighted = round(ss * confidence)
    sd = ([f"KI-Sentiment{'+' if ss >= 0 else ''}{ss}×conf{confidence:.1f}={ss_weighted:+d}"]
          if ss != 0 else [])

    # Sanity-Check gegen halluzinierte/veraltete Indikatoren — dieselbe Logik
    # wie im Dashboard (dataConsistency()). Bei Inkonsistenz wird der
    # Chart-Score wie in der Anzeige halbiert, statt die Warnung zu ignorieren.
    warnings = data_consistency(get_chart_item(isin), get_funda_item(isin))
    if warnings:
        cs_adj = cs * 0.5
        cd = cd + [f"⚠️Inkonsistent→Chart×0.5({cs}→{cs_adj:g})"]
        cs = cs_adj

    return cs + fs + ss_weighted, cs, cd, fs, fd, ss, sd

def score_reason(isin):
    ts, cs, cd, fs, fd, ss, sd = total_score(isin)
    c_item = get_chart_item(isin)
    f_item = get_funda_item(isin)
    c_text = c_item.get("begruendung", "") if c_item else ""
    f_text = f_item.get("begruendung", "") if f_item else ""
    _, _, s_text, _, _ = get_sentiment(isin)
    reason = (
        f"Score={ts} (Chart={cs}: {', '.join(cd)}; Funda={fs}: {', '.join(fd)}"
    )
    if ss != 0:
        reason += f"; KI-Sentiment={ss}"
    reason += f") | Chart: {c_text} | Funda: {f_text}"
    if s_text:
        reason += f" | KI: {s_text}"
    return reason

def budget_for_score(ts, buy_threshold):
    """Positionsgröße proportional zum Score: 1000€ Basis + 100€ je Punkt über Schwellwert, max 2500€."""
    base = 1000.0
    bonus = max(0, ts - buy_threshold) * 100.0
    return min(2500.0, base + bonus)


def is_watch_candidate(isin, chart_item, funda_item):
    """Kandidat noch nicht kaufbar (nicht genug Historie / Marker-Text).

    Zwei Signale zählen:
    1. Explizite Watch-Markierung im Fundamental- oder Chart-Text
       (Opportunity-Scan hinterlässt sie beim Einfügen).
    2. Chart-Indikatoren noch nicht belastbar: kein SMA200 vorhanden ODER
       kein `indicators_source` gesetzt (noch nie durch compute_indicators
       gelaufen). Dann fehlt die halbe Chart-Score-Basis.
    """
    for it in (chart_item, funda_item):
        if it and any(m in ((it.get("begruendung") or "").lower()) for m in WATCH_MARKERS):
            return True
    if chart_item is not None:
        if chart_item.get("sma_200") in (None, 0):
            return True
        if not chart_item.get("indicators_source"):
            return True
    return False


def compute_adaptive_buy_threshold(scores):
    """Adaptive Kaufschwelle aus den aktuellen Kandidatenscores.

    scores = Liste aller Nicht-Verkaufen-Nicht-Watch-Scores. Ergebnis ist
    max(BUY_FLOOR, 80er-Perzentil). Fallback auf BUY_FALLBACK_THRESHOLD,
    wenn zu wenige Datenpunkte für sinnvolles Perzentil vorliegen.
    """
    active = [s for s in scores if s is not None]
    if len(active) < BUY_MIN_CANDIDATES:
        return BUY_FALLBACK_THRESHOLD
    ordered = sorted(active)
    # 80. Perzentil ~ oberste 20 %
    idx = int(len(ordered) * BUY_PERCENTILE)
    idx = min(idx, len(ordered) - 1)
    return max(BUY_FLOOR, ordered[idx])

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map

isin_to_name = {}
sector_map = {}  # ISIN -> Sektor (aus Chartanalyse), für den Sektor-Cap.
for data_set in [chart_data, funda_data]:
    for sector, items in data_set.get("sektoren", {}).items():
        for item in items:
            if item.get("isin") and item.get("isin") not in isin_to_name:
                isin_to_name[item["isin"]] = item.get("wertpapier", "Unbekannt").replace(" (Teil 2)", "")
            if item.get("isin"):
                sector_map.setdefault(item["isin"], sector)


def sector_value(positions, sektor):
    return sum(p.get("boersenwert", 0) or 0 for p in positions
               if sector_map.get(p.get("isin")) == sektor)


def capped_budget(budget, isin, positions):
    """Kappt das Kaufbudget, falls es einen Sektor über MAX_SEKTOR_PCT_HARD triebe.

    Löst sek_val + x = CAP * (portfolio_value + x) nach x auf. Positionen ohne
    Sektor-Zuordnung sind vom Cap ausgenommen (kein Risiko, keine Bremse)."""
    sektor = sector_map.get(isin)
    if not sektor:
        return budget
    portfolio_value = sum(p.get("boersenwert", 0) or 0 for p in positions)
    sek_val = sector_value(positions, sektor)
    if portfolio_value + budget <= 0:
        return budget
    projected_pct = (sek_val + budget) / (portfolio_value + budget)
    if projected_pct <= MAX_SEKTOR_PCT_HARD:
        return budget
    allowed = (MAX_SEKTOR_PCT_HARD * portfolio_value - sek_val) / (1 - MAX_SEKTOR_PCT_HARD)
    return max(0.0, min(budget, allowed))

def get_live_price(isin):
    """EUR live price via the shared ticker map, guarded against wrong instruments.

    Returns None for ISINs without a reliable EUR listing (they must not become
    buy candidates) or when the price is implausible vs. the chart SMA50.
    """
    price, _src = ticker_map.eur_price(isin)
    if price is None:
        return None
    c_item = get_chart_item(isin) or {}
    if not ticker_map.plausible(price, c_item.get('sma_50')):
        return None
    return price

# ==========================================
# MARKT-REFERENZ (DAX) + AUTO-BETA für den relativen Stop-Loss
# ==========================================
# DAX als Benchmark. Beta wird pro Position automatisch aus ~1 Jahr
# Tagesrenditen geschätzt (Regression Aktie vs. DAX). Ohne verlässliche Daten
# fällt Beta auf 1.0 zurück ("im ersten Schritt 1:1, aber automatisch anpassend").
DAX_SYMBOL = "^GDAXI"
BETA_MIN, BETA_MAX, BETA_DEFAULT = 0.3, 2.5, 1.0
dax_now, dax_closes = ticker_map.fetch_index(DAX_SYMBOL)
_beta_cache = {}


def _daily_returns(closes):
    out = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev:
            out.append((closes[i] - prev) / prev)
    return out


def get_beta(isin):
    """Auto-Beta der Position ggü. DAX via Kovarianz/Varianz der Tagesrenditen.
    Geklemmt auf [BETA_MIN, BETA_MAX]; Fallback BETA_DEFAULT (1.0) bei zu wenig
    oder unzuverlässigen Daten."""
    if isin in _beta_cache:
        return _beta_cache[isin]
    beta = BETA_DEFAULT
    try:
        if dax_closes and len(dax_closes) >= 61:
            closes, _latest, _src = ticker_map.eur_history(isin)
            if closes and len(closes) >= 61:
                n = min(len(closes), len(dax_closes))
                s = _daily_returns(closes[-n:])
                d = _daily_returns(dax_closes[-n:])
                m = min(len(s), len(d))
                if m >= 60:
                    s, d = s[-m:], d[-m:]
                    md = sum(d) / m
                    var = sum((x - md) ** 2 for x in d)   # Summe; /m kürzt sich
                    if var > 0:
                        ms = sum(s) / m
                        cov = sum((s[i] - ms) * (d[i] - md) for i in range(m))
                        beta = max(BETA_MIN, min(BETA_MAX, cov / var))
    except Exception:
        beta = BETA_DEFAULT
    _beta_cache[isin] = round(beta, 3)
    return _beta_cache[isin]


fee_per_trade = 5.00
CAP_GAINS_TAX = 0.26375   # Kapitalertragsteuer + Soli, nur auf Gewinne
summary = []


def _today_iso():
    return datetime.now().strftime("%Y-%m-%d")


def _make_sell_record(p, price, notiz, begruendung):
    """Berechne Netto-Erlös (nach Gebühr & Steuer) und baue Verkaufs-Transaktion.

    Steuer greift nur bei tatsächlichem Gewinn (Brutto-Verlust ist steuerfrei).
    Der zurückgegebene `net_cash` gehört auf `current_cash` addiert, `tx`
    kommt in die Transaktionshistorie.
    """
    units = p["stueck"]
    revenue = (units * price) - fee_per_trade
    gv_brutto = revenue - p["investiert"]
    steuern = round(gv_brutto * CAP_GAINS_TAX, 2) if gv_brutto > 0 else 0.0
    net_cash = revenue - steuern
    tx = {
        "datum": _today_iso(),
        "typ": "Verkauf",
        "isin": p.get("isin"),
        "wertpapier": p.get("wertpapier", p.get("isin")),
        "stueck": units,
        "kurs": price,
        "gebuehr": fee_per_trade,
        "steuern": steuern,
        "gewinn_verlust": round(gv_brutto, 2),
        "gesamt": round(net_cash, 2),
        "notiz": notiz,
        "begruendung": begruendung,
    }
    return tx, net_cash


def _make_buy_record(isin, stock, units, price, ts, begruendung):
    """Baue Kauf-Transaktion. Rückgabewert `total_cost` gehört von `current_cash` abgezogen."""
    total_cost = units * price + fee_per_trade
    tx = {
        "datum": _today_iso(),
        "typ": "Kauf",
        "isin": isin,
        "wertpapier": stock,
        "stueck": units,
        "kurs": price,
        "gebuehr": fee_per_trade,
        "steuern": 0.0,
        "gewinn_verlust": 0.0,
        "gesamt": round(total_cost, 2),
        "notiz": f"Neukauf (Score={ts})",
        "begruendung": begruendung,
    }
    return tx, total_cost

# ==========================================
# PLANUNGSPHASE: ZIELPORTFOLIO MIT SCORING
# Kauf-Kandidaten: Score >= adaptivem BUY_THRESHOLD,
# kein explizites "Verkaufen" in chart UND funda, nicht Watch.
# ==========================================
all_isins = set()
for data_set in [chart_data, funda_data]:
    for sector, items in data_set.get("sektoren", {}).items():
        for item in items:
            if item.get("isin"):
                all_isins.add(item["isin"])

# Schritt 1: alle aktiven Scores sammeln (Watch/Verkauf/Veto aussortieren).
# Watch-Kandidaten wandern in eine Merkliste — sie werden nicht gekauft,
# bleiben aber sichtbar für Reporting/Dashboard.
active_scores = []
watch_list = []
for isin in all_isins:
    c_item = get_chart_item(isin)
    f_item = get_funda_item(isin)
    if not c_item or not f_item:
        continue
    c_emp = (c_item.get("empfehlung") or "").lower()
    f_emp = (f_item.get("empfehlung") or "").lower()
    if "verkauf" in c_emp or "verkauf" in f_emp:
        continue
    # Stufe 2: KI-Veto blockiert Neukäufe (kann nie welche erzeugen).
    _, veto, veto_reason, _, _ = get_sentiment(isin)
    if veto:
        summary.append(f"KI-Veto: Kauf von {c_item.get('wertpapier', isin)} ({isin}) blockiert. {veto_reason}")
        continue
    if is_watch_candidate(isin, c_item, f_item):
        ts_watch = total_score(isin)[0]
        watch_list.append((isin, ts_watch))
        continue
    ts = total_score(isin)[0]
    active_scores.append((isin, ts))

# Schritt 2: adaptive Schwelle aus den aktiven Scores bestimmen.
BUY_THRESHOLD = compute_adaptive_buy_threshold([ts for _, ts in active_scores])

# Schritt 3: Kandidaten oberhalb der adaptiven Schwelle selektieren.
scored_candidates = [(isin, ts) for isin, ts in active_scores if ts >= BUY_THRESHOLD]
scored_candidates.sort(key=lambda x: -x[1])

if watch_list:
    watch_list.sort(key=lambda x: -x[1])
    watch_names = [f"{isin_to_name.get(i, i)}({t})" for i, t in watch_list[:5]]
    summary.append(f"Watch-Modus: {len(watch_list)} Kandidat(en) noch nicht kaufbar "
                   f"(fehlende Historie). Top: {', '.join(watch_names)}.")
summary.append(f"Adaptive Kaufschwelle: {BUY_THRESHOLD} "
               f"(Floor {BUY_FLOOR}, {int(BUY_PERCENTILE*100)}er-Perzentil "
               f"aus {len(active_scores)} aktiven Kandidaten).")

live_prices = {}
target_isins_scored = []
for isin, ts in scored_candidates:
    price = get_live_price(isin)
    if price:
        live_prices[isin] = price
        target_isins_scored.append((isin, ts))

target_isins = [isin for isin, _ in target_isins_scored]

# ==========================================
# 1. STRATEGISCHER VERKAUF
# Auslöser: empfehlung=Verkaufen ODER Score < SELL_THRESHOLD
# ==========================================
positions_to_keep = []
sold_isins = set()  # in diesem Lauf verkauft -> kein Rückkauf im selben Lauf
for p in positions:
    isin = p.get("isin")
    stock = p.get("wertpapier", isin)

    c_item = get_chart_item(isin)
    f_item = get_funda_item(isin)
    c_emp = (c_item.get("empfehlung") or "").lower() if c_item else ""
    f_emp = (f_item.get("empfehlung") or "").lower() if f_item else ""
    ts = total_score(isin)[0]

    current_price = live_prices.get(isin) or get_live_price(isin) or p.get("boersenkurs", 0)
    if current_price:
        live_prices[isin] = current_price

    kaufkurs = p.get("kaufkurs", 0) or 0
    drawdown = ((current_price - kaufkurs) / kaufkurs) if (kaufkurs and current_price) else 0.0

    # Marktbereinigung: Alpha = relativer Drawdown SEIT DEM ANKER minus die
    # beta-erwartete DAX-Bewegung seit demselben Anker. Kurs- und DAX-Anker
    # (stop_ref_kurs, dax_ref) werden IMMER gemeinsam gesetzt, damit beide
    # denselben Zeithorizont haben (sonst würde ein Alt-Verlust fälschlich als
    # Alpha gewertet). Neukäufe verankern beim Kauf, Altpositionen beim ersten
    # Lauf auf heute (relative Uhr startet dann bei 0).
    beta = get_beta(isin)
    dax_ref = p.get("dax_ref")
    ref_kurs = p.get("stop_ref_kurs")
    rel_dd = None
    r_dax = None
    alpha = None
    if dax_ref and ref_kurs and dax_now and current_price:
        rel_dd = (current_price - ref_kurs) / ref_kurs
        r_dax = (dax_now - dax_ref) / dax_ref
        alpha = rel_dd - beta * r_dax

    sell = False
    sell_reason = ""
    if "verkauf" in c_emp or "verkauf" in f_emp:
        sell = True
        sell_reason = f"Explizites Verkaufen-Signal (Score={ts})"
    elif drawdown <= ABS_HARD_STOP_PCT:
        sell = True
        sell_reason = f"Absoluter Hard-Stop ({drawdown*100:.1f}% ≤ {ABS_HARD_STOP_PCT*100:.0f}%)"
    elif alpha is not None and rel_dd < 0 and alpha <= REL_STOP_PCT:
        sell = True
        sell_reason = (f"Relativer Stop: {alpha*100:.1f}% Underperformance vs. DAX "
                       f"(β={beta:.2f}, seit Anker: Kurs {rel_dd*100:+.1f}% / "
                       f"DAX {r_dax*100:+.1f}%) ≤ {REL_STOP_PCT*100:.0f}%")
    elif ts < SELL_THRESHOLD:
        sell = True
        sell_reason = f"Score unter Schwellwert ({ts} < {SELL_THRESHOLD})"

    if sell:
        begruendung = sell_reason + " | " + score_reason(isin)
        tx, net_cash = _make_sell_record(p, current_price,
                                         notiz=f"Strategischer Verkauf ({sell_reason})",
                                         begruendung=begruendung)
        current_cash += net_cash
        sold_isins.add(isin)
        summary.append(f"Strategischer Verkauf: {p['stueck']}x {stock} ({isin}) zu {current_price:.2f} EUR. {sell_reason}.")
        transactions.append(tx)
    else:
        p["boersenkurs"] = current_price
        p["boersenwert"] = round(p["stueck"] * p["boersenkurs"], 2)
        p["gewinn_verlust"] = round(p["boersenwert"] - p["investiert"], 2)
        p["score"] = ts
        p["beta"] = beta
        # Review-Flag: starkes Negativ-Sentiment auf BESTEHENDER Position ist
        # kein Verkaufsgrund (das entscheidet weiter der harte Score / Stop),
        # aber sichtbar machen statt stillschweigend zu ignorieren.
        sent_score, _, sent_reason, _, sent_kategorie = get_sentiment(isin)
        if sent_score <= REVIEW_FLAG_THRESHOLD:
            p["review_flag"] = True
            p["review_grund"] = f"KI-Sentiment {sent_score} ({sent_kategorie}): {sent_reason}"
        else:
            p.pop("review_flag", None)
            p.pop("review_grund", None)
        # Anker-Paar (Kurs + DAX) gemeinsam auf heute setzen, falls (noch) nicht
        # vorhanden — Altpositionen ohne Kaufdatum: relative Uhr startet bei 0.
        if dax_now and current_price and (not p.get("dax_ref") or not p.get("stop_ref_kurs")):
            p["dax_ref"] = round(dax_now, 2)
            p["stop_ref_kurs"] = round(current_price, 4)
        # TRAILING-STOP: macht die Position ein neues Hoch, wandert das Anker-Paar
        # (Höchststand-Referenz) mit nach oben. Der relative Stop misst den
        # beta-bereinigten Rückgang dann vom PEAK statt vom Einstieg — aufgelaufene
        # Gewinne werden so mitgesichert. Anker nur nach oben (Ratchet), nie zurück,
        # daher werden Gewinne nie wieder komplett hergegeben, bevor der Stop greift.
        elif dax_now and current_price and current_price > (p.get("stop_ref_kurs") or 0):
            p["stop_ref_kurs"] = round(current_price, 4)
            p["dax_ref"] = round(dax_now, 2)
        positions_to_keep.append(p)

positions = positions_to_keep

# ==========================================
# 2. ERMITTELN DES KAPITALBEDARFS
# Positionsgröße ist score-abhängig
# ==========================================
unowned_targets = [(isin, ts) for isin, ts in target_isins_scored
                   if not any(p.get("isin") == isin for p in positions)
                   and isin not in sold_isins]
total_needed_cash = sum(budget_for_score(ts, BUY_THRESHOLD) for _, ts in unowned_targets)

# ==========================================
# 3. REBALANCING (Schwache Halten-Positionen verkaufen)
# Sortiert nach schlechtestem Score (schwächste zuerst)
# ==========================================
halten_positions = [p for p in positions
                    if p.get("isin") not in target_isins
                    and p.get("score", 0) < REBALANCE_THRESHOLD]
halten_positions.sort(key=lambda p: (p.get("score", 0), p["gewinn_verlust"] / p["investiert"] if p["investiert"] > 0 else 0))

for p in halten_positions:
    if current_cash >= total_needed_cash:
        break
    isin = p.get("isin")
    stock = p.get("wertpapier", isin)
    price = p["boersenkurs"]
    begruendung = "Rebalancing | " + score_reason(isin)
    tx, net_cash = _make_sell_record(p, price,
                                     notiz="Rebalancing (Kapitalbeschaffung für Neukäufe)",
                                     begruendung=begruendung)
    current_cash += net_cash
    summary.append(f"Rebalancing-Verkauf: {p['stueck']}x {stock} ({isin}) zu {price:.2f} EUR (Score={p.get('score',0)}).")
    transactions.append(tx)
    positions.remove(p)

# ==========================================
# 4. NEUKÄUFE — höchster Score zuerst, Größe score-abhängig
# ==========================================
for isin, ts in unowned_targets:
    if isin not in live_prices:
        continue
    price = live_prices[isin]
    stock = isin_to_name.get(isin, isin)
    budget = budget_for_score(ts, BUY_THRESHOLD)
    # Mindest-Barreserve nie unterschreiten.
    spendable = current_cash - MIN_CASH_RESERVE
    budget_before_cap = min(budget, spendable)
    budget_for_this = capped_budget(budget_before_cap, isin, positions)
    if budget_for_this < MIN_ORDER_VALUE + fee_per_trade:
        if budget_for_this < budget_before_cap:
            summary.append(f"Sektor-Cap: Kauf von {stock} ({isin}) gekappt/blockiert "
                           f"(Sektor {sector_map.get(isin)} nahe/über {MAX_SEKTOR_PCT_HARD*100:.0f}%).")
        continue  # zu wenig freies Kapital für eine sinnvolle Order
    units_to_buy = int((budget_for_this - fee_per_trade) / price)
    order_value = units_to_buy * price
    if units_to_buy > 0 and order_value >= MIN_ORDER_VALUE:
        begruendung = score_reason(isin)
        tx, total_cost = _make_buy_record(isin, stock, units_to_buy, price, ts, begruendung)
        current_cash -= total_cost
        positions.append({
            "isin": isin,
            "wertpapier": stock,
            "stueck": units_to_buy,
            "kaufkurs": price,
            "boersenkurs": price,
            "investiert": round(units_to_buy * price, 2),
            "boersenwert": round(units_to_buy * price, 2),
            "gewinn_verlust": 0.0,
            "score": ts,
            "dax_ref": round(dax_now, 2) if dax_now else None,
            "stop_ref_kurs": price,
            "beta": get_beta(isin)
        })
        transactions.append(tx)
        summary.append(f"Kauf: {units_to_buy}x {stock} ({isin}) zu {price:.2f} EUR, Score={ts}, Budget={budget:.0f}€.")

portfolio_value = sum(p.get("boersenwert", 0) for p in positions)

if RECOMMEND:
    # Nichts am Depot ändern — nur Vorschläge als Entscheidungsgrundlage schreiben.
    new_trades = transactions[initial_tx_count:]
    recommendation = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "hinweis": ("Regelbasierter Vorschlag (Chart+Funda+KI-Sentiment, inkl. Veto). "
                    "Der Agent entscheidet autonom und kann abweichen."),
        "vorgeschlagene_trades": new_trades,
        "zusammenfassung": summary,
        "resultierender_barbestand": round(current_cash, 2),
        "resultierender_portfoliowert": round(portfolio_value, 2),
        "resultierendes_gesamtvermoegen": round(current_cash + portfolio_value, 2),
    }
    save_json(recommend_path, recommendation)
    print(f"[EMPFEHLUNGS-MODUS] {len(new_trades)} Trade-Vorschläge -> {recommend_path}")
    if summary:
        print("\n".join(summary))
    else:
        print("Vorschlag: keine Trades nötig, Zielportfolio erreicht.")
else:
    depot["aktueller_barbestand"] = round(current_cash, 2)
    depot["portfoliowert"] = round(portfolio_value, 2)
    depot["gesamtvermoegen"] = round(current_cash + portfolio_value, 2)
    depot["positionen"] = positions
    depot["transaktionshistorie"] = transactions
    data["depot"] = depot

    save_json(depot_path, data)

    if summary:
        print("\n".join(summary))
    else:
        print("Keine Transaktionen notwendig. Zielportfolio ist erreicht.")
