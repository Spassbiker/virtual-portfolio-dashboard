import json
import os
import urllib.request
from datetime import datetime

base_dir = "/home/ubuntu/.openclaw/workspace"
# Wir arbeiten im aktuellen Verzeichnis, da wir im Temp Repo sind.
depot_path = "depot_status.json"

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

def normalize_name(name):
    return name.replace(" (Teil 2)", "").replace(" S.p.a.", "").replace(" SpA", "").replace(" SA", "").replace(" SE", "").strip()

def get_recommendation(data_json, stock_name):
    for sector, items in data_json.get("sektoren", {}).items():
        for item in items:
            if normalize_name(item["wertpapier"]) == stock_name:
                return item.get("empfehlung", "").lower()
    return "unbekannt"

yf_tickers = {
    'Leonardo': 'LDO.MI',
    'Siemens Energy': 'ENR.DE',
    'Rolls-Royce': 'RRU.DE',
    'Thales': 'HO.PA',
    'ASML': 'ASML.AS',
    'MTU Aero Engines': 'MTX.DE',
    'Rheinmetall': 'RHM.DE',
    'SAP': 'SAP.DE',
    'Safran': 'SAF.PA',
    'E.ON': 'EOAN.DE',
    'RWE': 'RWE.DE',
    'Infineon': 'IFX.DE',
    'Airbus': 'AIR.PA',
    'Planet Labs': 'PL',
    'Eutelsat': 'ETL.PA'
}

isin_mapping = {
    'Leonardo': 'IT0003856405',
    'Siemens Energy': 'DE000ENER6Y0',
    'Rolls-Royce': 'GB00B63H8491',
    'Thales': 'FR0000121329',
    'ASML': 'NL0010273215',
    'MTU Aero Engines': 'DE000A0D9PT0',
    'Rheinmetall': 'DE0007030009',
    'SAP': 'DE0007164600',
    'Safran': 'FR0000073272',
    'E.ON': 'DE000ENAG999',
    'RWE': 'DE0007037129',
    'Infineon': 'DE0006231004',
    'Airbus': 'NL0000235190',
    'Planet Labs': 'US72703X1054',
    'Encavis': 'DE0006095003',
    'Eutelsat': 'FR0010221234'
}

def get_live_price(stock):
    if stock not in yf_tickers:
        return None
    ticker = yf_tickers[stock]
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            jdata = json.loads(response.read().decode())
            return jdata['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception as e:
        print(f"Error fetching live price for {stock}: {e}")
        return None

fee_per_trade = 5.00
summary = []

# ==========================================
# 1. STRATEGISCHER VERKAUF (Verkauf-Signal)
# ==========================================
positions_to_keep = []
for p in positions:
    stock = p["wertpapier"]
    chart_rec = get_recommendation(chart_data, stock)
    funda_rec = get_recommendation(funda_data, stock)
    
    current_price = get_live_price(stock) or p["boersenkurs"]
    
    if "verkauf" in chart_rec or "verkauf" in funda_rec:
        units = p["stueck"]
        revenue = (units * current_price) - fee_per_trade
        current_cash += revenue
        summary.append(f"Strategischer Verkauf: {units}x {stock} zu {current_price:.2f} EUR (Erlös: {revenue:.2f} EUR). Grund: 'Verkaufen'-Signal.")
        transactions.append({
            "datum": datetime.now().strftime("%Y-%m-%d"),
            "typ": "Verkauf",
            "isin": p.get("isin", ""),
            "wertpapier": stock,
            "stueck": units,
            "kurs": current_price,
            "gebuehr": fee_per_trade,
            "gesamt": round(revenue, 2),
            "notiz": "Strategischer Verkauf ('Verkaufen'-Signal)"
        })
    else:
        p["boersenkurs"] = current_price
        p["boersenwert"] = round(p["stueck"] * p["boersenkurs"], 2)
        p["gewinn_verlust"] = round(p["boersenwert"] - p["investiert"], 2)
        positions_to_keep.append(p)
        
positions = positions_to_keep

# ==========================================
# ZIELKANDIDATEN IDENTIFIZIEREN
# ==========================================
chart_buys = set()
for sector, items in chart_data.get("sektoren", {}).items():
    for item in items:
        if "kauf" in item.get("empfehlung", "").lower():
            chart_buys.add(normalize_name(item["wertpapier"]))

funda_buys = set()
for sector, items in funda_data.get("sektoren", {}).items():
    for item in items:
        if "kauf" in item.get("empfehlung", "").lower():
            funda_buys.add(normalize_name(item["wertpapier"]))

target_stocks = list(chart_buys.intersection(funda_buys))

# ==========================================
# 2. NEUKÄUFE & REBALANCING
# ==========================================
budget_per_stock = 1500.0

for stock in target_stocks:
    already_owned = any(p["wertpapier"] == stock for p in positions)
    if already_owned: continue
    
    price = get_live_price(stock)
    if not price: continue
    
    isin = isin_mapping.get(stock, "")
    units_to_buy = int((budget_per_stock - fee_per_trade) / price)
    if units_to_buy <= 0: continue
    total_cost = (units_to_buy * price) + fee_per_trade
    
    # Rebalancing
    if current_cash < total_cost:
        def sort_key(p):
            c_rec = get_recommendation(chart_data, p["wertpapier"])
            f_rec = get_recommendation(funda_data, p["wertpapier"])
            is_halten = 1 if ("halt" in c_rec or "halt" in f_rec) else 0
            profit_margin = p["gewinn_verlust"] / p["investiert"] if p["investiert"] > 0 else 0
            return (-is_halten, profit_margin)
        
        positions.sort(key=sort_key)
        
        rebalanced = False
        for weak_p in positions:
            if weak_p["stueck"] <= 0: continue
            
            deficit = total_cost - current_cash + fee_per_trade
            weak_price = weak_p["boersenkurs"]
            units_to_sell = int((deficit / weak_price)) + 1
            
            if units_to_sell > weak_p["stueck"]:
                units_to_sell = weak_p["stueck"]
                
            if units_to_sell > 0:
                revenue = (units_to_sell * weak_price) - fee_per_trade
                current_cash += revenue
                weak_p["stueck"] -= units_to_sell
                weak_p["investiert"] = round(weak_p["stueck"] * weak_p["kaufkurs"], 2)
                weak_p["boersenwert"] = round(weak_p["stueck"] * weak_p["boersenkurs"], 2)
                weak_p["gewinn_verlust"] = round(weak_p["boersenwert"] - weak_p["investiert"], 2)
                
                summary.append(f"Rebalancing-Verkauf: {units_to_sell}x {weak_p['wertpapier']} (Erlös: {revenue:.2f} EUR).")
                transactions.append({
                    "datum": datetime.now().strftime("%Y-%m-%d"),
                    "typ": "Verkauf",
                    "isin": weak_p.get("isin", ""),
                    "wertpapier": weak_p["wertpapier"],
                    "stueck": units_to_sell,
                    "kurs": weak_price,
                    "gebuehr": fee_per_trade,
                    "gesamt": round(revenue, 2),
                    "notiz": f"Rebalancing für Neukauf von {stock}"
                })
                
            if current_cash >= total_cost:
                rebalanced = True
                break
                
        positions = [p for p in positions if p["stueck"] > 0]
        
        if not rebalanced:
            continue

    # Kaufen
    if current_cash >= total_cost:
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
        transactions.append({
            "datum": datetime.now().strftime("%Y-%m-%d"),
            "typ": "Kauf",
            "isin": isin,
            "wertpapier": stock,
            "stueck": units_to_buy,
            "kurs": price,
            "gebuehr": fee_per_trade,
            "gesamt": round(total_cost, 2),
            "notiz": "Neukauf (Kauf-Signal)"
        })
        summary.append(f"Kauf: {units_to_buy}x {stock} zu {price:.2f} EUR (Gesamt: {total_cost:.2f} EUR).")

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
    print("Keine Transaktionen notwendig. Depot ist optimal aufgestellt.")
