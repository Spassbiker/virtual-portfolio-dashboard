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

def get_recommendation(data_json, isin):
    if not isin: return "unbekannt"
    for sector, items in data_json.get("sektoren", {}).items():
        for item in items:
            if item.get("isin") == isin:
                return item.get("empfehlung", "").lower()
    return "unbekannt"

def get_reason(data_json, isin):
    if not isin: return ""
    for sector, items in data_json.get("sektoren", {}).items():
        for item in items:
            if item.get("isin") == isin:
                return item.get("begruendung", "")
    return ""

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

# Dynamically construct names mapping for new purchases
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
# PLANUNGSPHASE: ZIELPORTFOLIO ERMITTELN (über ISIN)
# ==========================================
chart_buys = set()
for sector, items in chart_data.get("sektoren", {}).items():
    for item in items:
        if item.get("empfehlung", "").lower() == "kaufen" and item.get("isin"):
            chart_buys.add(item["isin"])

funda_buys = set()
for sector, items in funda_data.get("sektoren", {}).items():
    for item in items:
        if item.get("empfehlung", "").lower() == "kaufen" and item.get("isin"):
            funda_buys.add(item["isin"])

target_isins_raw = list(chart_buys.intersection(funda_buys))
target_isins_raw.sort() 

live_prices = {}
target_isins = []
for isin in target_isins_raw:
    price = get_live_price(isin)
    if price:
        live_prices[isin] = price
        target_isins.append(isin)

# ==========================================
# 1. STRATEGISCHER VERKAUF (Verkauf-Signal über ISIN)
# ==========================================
positions_to_keep = []
for p in positions:
    isin = p.get("isin")
    stock = p.get("wertpapier", isin)
    
    chart_rec = get_recommendation(chart_data, isin)
    funda_rec = get_recommendation(funda_data, isin)
    
    current_price = live_prices.get(isin) or get_live_price(isin) or p.get("boersenkurs", 0)
    
    if "verkauf" in chart_rec or "verkauf" in funda_rec:
        units = p["stueck"]
        revenue = (units * current_price) - fee_per_trade
        investiert = p["investiert"]
        gewinn_verlust_brutto = revenue - investiert
        steuern = 0.0
        if gewinn_verlust_brutto > 0:
            steuern = round(gewinn_verlust_brutto * 0.26375, 2)
        current_cash += (revenue - steuern)
        
        c_reason = get_reason(chart_data, isin)
        f_reason = get_reason(funda_data, isin)
        begruendung = f"Chartanalyse: {c_reason} | Fundamentalanalyse: {f_reason}"
        
        summary.append(f"Strategischer Verkauf: {units}x {stock} ({isin}) zu {current_price:.2f} EUR. Grund: 'Verkaufen'-Signal.")
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
            "notiz": "Strategischer Verkauf ('Verkaufen'-Signal)",
            "begruendung": begruendung
        })
    else:
        p["boersenkurs"] = current_price
        p["boersenwert"] = round(p["stueck"] * p["boersenkurs"], 2)
        p["gewinn_verlust"] = round(p["boersenwert"] - p["investiert"], 2)
        positions_to_keep.append(p)
        
positions = positions_to_keep

# ==========================================
# 2. ERMITTELN DES KAPITALBEDARFS
# ==========================================
budget_per_stock = 1500.0
unowned_targets = [t for t in target_isins if not any(p.get("isin") == t for p in positions)]
total_needed_cash = len(unowned_targets) * budget_per_stock

# ==========================================
# 3. REBALANCING (NUR 'Halten' Werte verkaufen)
# ==========================================
halten_positions = [p for p in positions if p.get("isin") not in target_isins]
halten_positions.sort(key=lambda p: p["gewinn_verlust"] / p["investiert"] if p["investiert"] > 0 else 0)

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
    
    c_reason = get_reason(chart_data, isin)
    f_reason = get_reason(funda_data, isin)
    begruendung = f"Chartanalyse: {c_reason} | Fundamentalanalyse: {f_reason}"
    
    summary.append(f"Rebalancing-Verkauf: {units}x {stock} ({isin}) zu {price:.2f} EUR, um Liquidität für Zielportfolio zu schaffen.")
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
# 4. NEUKÄUFE AUSFÜHREN
# ==========================================
for isin in unowned_targets:
    price = live_prices[isin]
    stock = isin_to_name.get(isin, isin)
    
    budget_for_this = min(budget_per_stock, current_cash)
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
            "gewinn_verlust": 0.0
        })
        c_reason = get_reason(chart_data, isin)
        f_reason = get_reason(funda_data, isin)
        begruendung = f"Chartanalyse: {c_reason} | Fundamentalanalyse: {f_reason}"
        
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
            "notiz": "Neukauf (Kauf-Signal)",
            "begruendung": begruendung
        })
        summary.append(f"Kauf: {units_to_buy}x {stock} ({isin}) zu {price:.2f} EUR (Gesamt: {total_cost:.2f} EUR).")

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
