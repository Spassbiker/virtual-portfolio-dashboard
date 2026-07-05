import json
import os
import urllib.request
from datetime import datetime

base_dir = "/home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data"
depot_path = os.path.join(base_dir, "depot_status.json")

with open(depot_path, "r") as f:
    data = json.load(f)

depot = data.get("depot", {})
current_cash = depot.get("aktueller_barbestand", 10000.0)
positions = depot.get("positionen", [])
transactions = depot.get("transaktionshistorie", [])

with open(os.path.join(base_dir, "chartanalyse_ergebnisse.json"), "r") as f:
    chart_data = json.load(f)
with open(os.path.join(base_dir, "fundamentalanalyse_ergebnisse.json"), "r") as f:
    funda_data = json.load(f)

# ==========================================
# SCORING-SYSTEM
# ==========================================

# Minimum total score to enter target portfolio (Kauf-Kandidat)
BUY_THRESHOLD = 8
# Score below this triggers Verkauf für bestehende Positionen
SELL_THRESHOLD = 4

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

    emp = item.get("empfehlung", "").lower()
    if "kaufen" in emp:
        score += 3; details.append("Empf.+3")
    elif "verkauf" in emp:
        score -= 5; details.append("Empf.-5")

    trend = item.get("trend", "").lower()
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

def compute_funda_score(isin):
    """Fundamental-Score (max ~9, min ~-7)."""
    item = get_funda_item(isin)
    if not item:
        return 0, []
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
    return cs + fs, cs, cd, fs, fd

def score_reason(isin):
    ts, cs, cd, fs, fd = total_score(isin)
    c_item = get_chart_item(isin)
    f_item = get_funda_item(isin)
    c_text = c_item.get("begruendung", "") if c_item else ""
    f_text = f_item.get("begruendung", "") if f_item else ""
    indicators = ", ".join(cd + fd)
    return (
        f"Score={ts} (Chart={cs}: {', '.join(cd)}; Funda={fs}: {', '.join(fd)}) | "
        f"Chart: {c_text} | Funda: {f_text}"
    )

def budget_for_score(ts):
    """Positionsgröße proportional zum Score: 1000€ Basis + 100€ je Punkt über Schwellwert, max 2500€."""
    base = 1000.0
    bonus = max(0, ts - BUY_THRESHOLD) * 100.0
    return min(2500.0, base + bonus)

isin_to_ticker = {
    'IT0003856405': 'LDO.MI', 'DE000ENER6Y0': 'ENR.DE', 'GB00B63H8491': 'RRU.DE',
    'FR0000121329': 'HO.PA', 'NL0010273215': 'ASML.AS', 'DE000A0D9PT0': 'MTX.DE',
    'DE0007030009': 'RHM.DE', 'DE0007164600': 'SAP.DE', 'FR0000073272': 'SAF.PA',
    'DE000ENAG999': 'EOAN.DE', 'DE0007037129': 'RWE.DE', 'DE0006231004': 'IFX.DE',
    'NL0000235190': 'AIR.PA', 'US72703X1063': '85H1.DE', 'DE0006095003': 'ECV.DE',
    'FR0010221234': 'ETL.PA', 'DE000HAG0005': 'HAG.DE', 'DE000A0DJ6J9': 'S92.DE',
    'DE000A0D6554': 'NDX1.DE', 'DE0005936124': 'OHB.DE', 'DE000A2YN900': 'TMV.DE',
    'DE000A2E4K43': 'DHER.DE', 'DE0005557508': 'DTE.DE', 'DE000A0WMPJ6': 'AIXA.DE',
    'DK0061539921': 'VWS.CO', 'DK0060094928': 'ORSTED.CO', 'GB0002634946': 'BA.L',
    'US65339F1012': 'NEE', 'US6668071029': 'NOC', 'US3695501086': 'GD',
    'US5398301094': 'LMT', 'FR0014004L86': 'AM.PA', 'US0970231058': 'BA',
    'US0003611052': 'AIR', 'US4282911084': 'HXL', 'LU0088087324': 'SESG.PA',
    'US57778K1051': 'MAXR', 'US7731221062': 'RKLB', 'US46269C1027': 'IRDM',
    'IL0010825102': 'GILT', 'US79466L3024': 'CRM', 'US68389X1054': 'ORCL',
    'US67066G1040': 'NVDA', 'US5949181045': 'MSFT', 'US02079K3059': 'GOOG'
}

isin_to_name = {}
for data_set in [chart_data, funda_data]:
    for sector, items in data_set.get("sektoren", {}).items():
        for item in items:
            if item.get("isin") and item.get("isin") not in isin_to_name:
                isin_to_name[item["isin"]] = item.get("wertpapier", "Unbekannt").replace(" (Teil 2)", "")

def get_live_price(isin):
    if isin not in isin_to_ticker: return None
    ticker = isin_to_ticker[isin]
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            jdata = json.loads(response.read().decode())
            return jdata['chart']['result'][0]['meta']['regularMarketPrice']
    except:
        return None

fee_per_trade = 5.00
summary = []

# ==========================================
# PLANUNGSPHASE: ZIELPORTFOLIO MIT SCORING
# Kauf-Kandidaten: Score >= BUY_THRESHOLD,
# kein explizites "Verkaufen" in chart UND funda
# ==========================================
all_isins = set()
for data_set in [chart_data, funda_data]:
    for sector, items in data_set.get("sektoren", {}).items():
        for item in items:
            if item.get("isin"):
                all_isins.add(item["isin"])

scored_candidates = []
for isin in all_isins:
    c_item = get_chart_item(isin)
    f_item = get_funda_item(isin)
    if not c_item or not f_item:
        continue
    c_emp = c_item.get("empfehlung", "").lower()
    f_emp = (f_item.get("empfehlung") or "").lower()
    if "verkauf" in c_emp or "verkauf" in f_emp:
        continue
    ts, cs, cd, fs, fd = total_score(isin)
    if ts >= BUY_THRESHOLD:
        scored_candidates.append((isin, ts))

# Sortiert nach Score absteigend
scored_candidates.sort(key=lambda x: -x[1])

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
for p in positions:
    isin = p.get("isin")
    stock = p.get("wertpapier", isin)

    c_item = get_chart_item(isin)
    f_item = get_funda_item(isin)
    c_emp = c_item.get("empfehlung", "").lower() if c_item else ""
    f_emp = (f_item.get("empfehlung") or "").lower() if f_item else ""
    ts, _, _, _, _ = total_score(isin)

    current_price = live_prices.get(isin) or get_live_price(isin) or p.get("boersenkurs", 0)
    if current_price:
        live_prices[isin] = current_price

    sell = False
    sell_reason = ""
    if "verkauf" in c_emp or "verkauf" in f_emp:
        sell = True
        sell_reason = f"Explizites Verkaufen-Signal (Score={ts})"
    elif ts < SELL_THRESHOLD:
        sell = True
        sell_reason = f"Score unter Schwellwert ({ts} < {SELL_THRESHOLD})"

    if sell:
        units = p["stueck"]
        revenue = (units * current_price) - fee_per_trade
        investiert = p["investiert"]
        gewinn_verlust_brutto = revenue - investiert
        steuern = 0.0
        if gewinn_verlust_brutto > 0:
            steuern = round(gewinn_verlust_brutto * 0.26375, 2)
        current_cash += (revenue - steuern)
        begruendung = sell_reason + " | " + score_reason(isin)
        summary.append(f"Strategischer Verkauf: {units}x {stock} ({isin}) zu {current_price:.2f} EUR. {sell_reason}.")
        transactions.append({
            "datum": datetime.now().strftime("%Y-%m-%d"),
            "typ": "Verkauf",
            "isin": isin,
            "wertpapier": stock,
            "stueck": units,
            "kurs": current_price,
            "gebuehr": fee_per_trade,
            "steuern": steuern,
            "gewinn_verlust": round(gewinn_verlust_brutto, 2),
            "gesamt": round(revenue - steuern, 2),
            "notiz": f"Strategischer Verkauf ({sell_reason})",
            "begruendung": begruendung
        })
    else:
        p["boersenkurs"] = current_price
        p["boersenwert"] = round(p["stueck"] * p["boersenkurs"], 2)
        p["gewinn_verlust"] = round(p["boersenwert"] - p["investiert"], 2)
        p["score"] = ts
        positions_to_keep.append(p)

positions = positions_to_keep

# ==========================================
# 2. ERMITTELN DES KAPITALBEDARFS
# Positionsgröße ist score-abhängig
# ==========================================
unowned_targets = [(isin, ts) for isin, ts in target_isins_scored
                   if not any(p.get("isin") == isin for p in positions)]
total_needed_cash = sum(budget_for_score(ts) for _, ts in unowned_targets)

# ==========================================
# 3. REBALANCING (Schwache Halten-Positionen verkaufen)
# Sortiert nach schlechtestem Score (schwächste zuerst)
# ==========================================
halten_positions = [p for p in positions if p.get("isin") not in target_isins]
halten_positions.sort(key=lambda p: (p.get("score", 0), p["gewinn_verlust"] / p["investiert"] if p["investiert"] > 0 else 0))

for p in halten_positions:
    if current_cash >= total_needed_cash:
        break
    isin = p.get("isin")
    stock = p.get("wertpapier", isin)
    units = p["stueck"]
    price = p["boersenkurs"]
    revenue = (units * price) - fee_per_trade
    investiert = p["investiert"]
    gewinn_verlust_brutto = revenue - investiert
    steuern = 0.0
    if gewinn_verlust_brutto > 0:
        steuern = round(gewinn_verlust_brutto * 0.26375, 2)
    current_cash += (revenue - steuern)
    begruendung = f"Rebalancing | " + score_reason(isin)
    summary.append(f"Rebalancing-Verkauf: {units}x {stock} ({isin}) zu {price:.2f} EUR (Score={p.get('score',0)}).")
    transactions.append({
        "datum": datetime.now().strftime("%Y-%m-%d"),
        "typ": "Verkauf",
        "isin": isin,
        "wertpapier": stock,
        "stueck": units,
        "kurs": price,
        "gebuehr": fee_per_trade,
        "steuern": steuern,
        "gewinn_verlust": round(gewinn_verlust_brutto, 2),
        "gesamt": round(revenue - steuern, 2),
        "notiz": "Rebalancing (Kapitalbeschaffung für Neukäufe)",
        "begruendung": begruendung
    })
    positions.remove(p)

# ==========================================
# 4. NEUKÄUFE — höchster Score zuerst, Größe score-abhängig
# ==========================================
for isin, ts in unowned_targets:
    if isin not in live_prices:
        continue
    price = live_prices[isin]
    stock = isin_to_name.get(isin, isin)
    budget = budget_for_score(ts)
    budget_for_this = min(budget, current_cash)
    units_to_buy = int((budget_for_this - fee_per_trade) / price)
    if units_to_buy > 0:
        total_cost = (units_to_buy * price) + fee_per_trade
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
            "score": ts
        })
        begruendung = score_reason(isin)
        transactions.append({
            "datum": datetime.now().strftime("%Y-%m-%d"),
            "typ": "Kauf",
            "isin": isin,
            "wertpapier": stock,
            "stueck": units_to_buy,
            "kurs": price,
            "gebuehr": fee_per_trade,
            "steuern": 0.0,
            "gewinn_verlust": 0.0,
            "gesamt": round(total_cost, 2),
            "notiz": f"Neukauf (Score={ts})",
            "begruendung": begruendung
        })
        summary.append(f"Kauf: {units_to_buy}x {stock} ({isin}) zu {price:.2f} EUR, Score={ts}, Budget={budget:.0f}€.")

portfolio_value = sum(p.get("boersenwert", 0) for p in positions)
depot["aktueller_barbestand"] = round(current_cash, 2)
depot["portfoliowert"] = round(portfolio_value, 2)
depot["gesamtvermoegen"] = round(current_cash + portfolio_value, 2)
depot["positionen"] = positions
depot["transaktionshistorie"] = transactions
data["depot"] = depot

with open(depot_path, "w") as f:
    json.dump(data, f, indent=2)

if summary:
    print("\n".join(summary))
else:
    print("Keine Transaktionen notwendig. Zielportfolio ist erreicht.")
