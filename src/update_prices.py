import urllib.request
import json
import os

base_dir = "/home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data"
depot_path = os.path.join(base_dir, "depot_status.json")
funda_path = os.path.join(base_dir, "fundamentalanalyse_ergebnisse.json")
chart_path = os.path.join(base_dir, "chartanalyse_ergebnisse.json")

# Load all files
with open(depot_path, "r", encoding="utf-8") as f:
    depot_data = json.load(f)

with open(funda_path, "r", encoding="utf-8") as f:
    funda_data = json.load(f)

with open(chart_path, "r", encoding="utf-8") as f:
    chart_data = json.load(f)

# Collect all ISINs
isins_to_fetch = set()

for p in depot_data.get('depot', {}).get('positionen', []):
    if p.get('isin'):
        isins_to_fetch.add(p['isin'])

for sector, items in funda_data.get('sektoren', {}).items():
    for item in items:
        if item.get('isin'):
            isins_to_fetch.add(item['isin'])

for sector, items in chart_data.get('sektoren', {}).items():
    for item in items:
        if item.get('isin'):
            isins_to_fetch.add(item['isin'])

prices = {}
for isin in isins_to_fetch:
    try:
        req = urllib.request.Request(f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            quotes = data.get('quotes', [])
            
            ticker = None
            for q in quotes:
                sym = q.get('symbol', '')
                if sym.endswith('.DE') or sym.endswith('.F') or sym.endswith('.MI') or sym.endswith('.PA') or sym.endswith('.AS'):
                    ticker = sym
                    break
            
            if not ticker and quotes:
                ticker = quotes[0].get('symbol')
                
            if ticker:
                req2 = urllib.request.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d", headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req2) as response2:
                    data2 = json.loads(response2.read())
                    price = data2['chart']['result'][0]['meta']['regularMarketPrice']
                    prices[isin] = round(price, 3)
    except Exception as e:
        print(f"Error fetching {isin}: {e}")

# Update Depot
portfoliowert = 0.0
for p in depot_data['depot']['positionen']:
    isin = p.get('isin')
    if isin in prices:
        p['boersenkurs'] = prices[isin]
    
    p['boersenwert'] = round(p['stueck'] * p['boersenkurs'], 2)
    p['gewinn_verlust'] = round(p['boersenwert'] - p['investiert'], 2)
    portfoliowert += p['boersenwert']

depot_data['depot']['portfoliowert'] = round(portfoliowert, 2)
depot_data['depot']['gesamtvermoegen'] = round(portfoliowert + depot_data['depot']['aktueller_barbestand'], 2)

with open(depot_path, 'w', encoding='utf-8') as f:
    json.dump(depot_data, f, indent=2)

# Update Funda
for sector, items in funda_data.get('sektoren', {}).items():
    for item in items:
        isin = item.get('isin')
        if isin in prices:
            item['aktueller_kurs'] = prices[isin]

with open(funda_path, 'w', encoding='utf-8') as f:
    json.dump(funda_data, f, indent=2)

# Update Chart
for sector, items in chart_data.get('sektoren', {}).items():
    for item in items:
        isin = item.get('isin')
        if isin in prices:
            item['aktueller_kurs'] = prices[isin]

with open(chart_path, 'w', encoding='utf-8') as f:
    json.dump(chart_data, f, indent=2)

print(f"Prices updated successfully. Found {len(prices)} prices.")
