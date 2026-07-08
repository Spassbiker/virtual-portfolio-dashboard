import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map

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

def fetch_eur_price(isin):
    """Returns an EUR price via the shared ticker map, or None if skipped/unresolved."""
    cands = ticker_map.candidates(isin)
    if not cands:
        return None, None
    for cand in cands:
        price, currency = ticker_map.fetch_price(cand)
        if price is not None and currency == 'EUR':
            return price, cand
    return None, None

prices = {}
for isin in isins_to_fetch:
    try:
        if ticker_map.is_skipped(isin):
            print(f"  SKIP {isin}: kein verlässliches EUR-Listing (übersprungen)")
            continue
        price, used = fetch_eur_price(isin)
        if price is not None:
            prices[isin] = price
            print(f"  OK {isin}: {price} EUR ({used})")
        else:
            print(f"  SKIP {isin}: kein EUR-Ticker aufgelöst")
    except Exception as e:
        print(f"  ERROR {isin}: {e}")

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
