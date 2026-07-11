import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from paths import (
    DEPOT as depot_path,
    FUNDA as funda_path,
    CHART as chart_path,
    ETF_KATALOG as etf_katalog_path,
    load_json,
    save_json,
)

depot_data = load_json(depot_path, {})
funda_data = load_json(funda_path, {})
chart_data = load_json(chart_path, {})
etf_katalog_data = load_json(etf_katalog_path, {})

# Collect all ISINs
isins_to_fetch = set()

for p in depot_data.get('depot', {}).get('positionen', []):
    if p.get('isin'):
        isins_to_fetch.add(p['isin'])

for p in depot_data.get('etf_depot', {}).get('positionen', []):
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

for sector, items in etf_katalog_data.get('sektoren', {}).items():
    for item in items:
        if item.get('isin'):
            isins_to_fetch.add(item['isin'])

prices = {}
for isin in isins_to_fetch:
    try:
        if ticker_map.is_skipped(isin):
            print(f"  SKIP {isin}: kein verlässliches EUR-/USD-Listing (übersprungen)")
            continue
        price, used = ticker_map.eur_price(isin)
        if price is not None:
            prices[isin] = price
            print(f"  OK {isin}: {price} EUR ({used})")
        else:
            print(f"  SKIP {isin}: kein Kurs aufgelöst")
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

# Update ETF-Sleeve
if 'etf_depot' in depot_data:
    etf_portfoliowert = 0.0
    for p in depot_data['etf_depot']['positionen']:
        isin = p.get('isin')
        if isin in prices:
            p['boersenkurs'] = prices[isin]

        p['boersenwert'] = round(p['stueck'] * p['boersenkurs'], 2)
        p['gewinn_verlust'] = round(p['boersenwert'] - p['investiert'], 2)
        etf_portfoliowert += p['boersenwert']

    depot_data['etf_depot']['portfoliowert'] = round(etf_portfoliowert, 2)
    depot_data['etf_depot']['gesamtvermoegen'] = round(
        etf_portfoliowert + depot_data['etf_depot']['aktueller_barbestand'], 2
    )

save_json(depot_path, depot_data)

# Update Funda
for sector, items in funda_data.get('sektoren', {}).items():
    for item in items:
        isin = item.get('isin')
        if isin in prices:
            item['aktueller_kurs'] = prices[isin]

save_json(funda_path, funda_data)

# Update Chart
for sector, items in chart_data.get('sektoren', {}).items():
    for item in items:
        isin = item.get('isin')
        if isin in prices:
            item['aktueller_kurs'] = prices[isin]

save_json(chart_path, chart_data)

# Update ETF-Katalog
for sector, items in etf_katalog_data.get('sektoren', {}).items():
    for item in items:
        isin = item.get('isin')
        if isin in prices:
            item['aktueller_kurs'] = prices[isin]

save_json(etf_katalog_path, etf_katalog_data)

print(f"Prices updated successfully. Found {len(prices)} prices.")
