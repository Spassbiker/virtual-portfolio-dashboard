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

EUR_SUFFIXES = ('.DE', '.F', '.MI', '.PA', '.AS', '.BR', '.LS', '.MC', '.VI', '.HE', '.CO', '.OL', '.ST')

# Explicit EUR ticker overrides for ISINs where auto-detection fails.
# Use the XETRA (.DE) or Frankfurt (.F) ticker — verify on finance.yahoo.com if unsure.
ISIN_TO_EUR_TICKER = {
    'US67066G1040': 'NVD.DE',   # Nvidia (XETRA: NVD, not NVDA which is a fund)
}

VALID_INSTRUMENT_TYPES = ('EQUITY', 'ETF')

def fetch_price_for_ticker(ticker):
    """Returns (price, currency) or (None, None) on error or wrong instrument type."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        meta = data['chart']['result'][0]['meta']
        instrument_type = meta.get('instrumentType', '')
        if instrument_type not in VALID_INSTRUMENT_TYPES:
            return None, None  # e.g. MUTUALFUND, INDEX — wrong instrument
        return round(meta['regularMarketPrice'], 3), meta.get('currency', '')

def fetch_eur_price(isin):
    """Returns EUR price or None. Logs currency issues."""
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    quotes = data.get('quotes', [])

    # First pass: prefer known EUR exchange suffixes
    eur_ticker = None
    base_ticker = None
    for q in quotes:
        sym = q.get('symbol', '')
        if any(sym.endswith(s) for s in EUR_SUFFIXES):
            if eur_ticker is None:
                eur_ticker = sym
        if base_ticker is None:
            base_ticker = sym

    # Try EUR-exchange ticker from search results
    if eur_ticker:
        try:
            price, currency = fetch_price_for_ticker(eur_ticker)
            if currency == 'EUR':
                return price
            print(f"  WARNING {isin}: ticker {eur_ticker} has currency={currency}, trying fallbacks")
        except Exception as e:
            print(f"  WARNING {isin}: {eur_ticker} failed ({e}), trying fallbacks")

    # Second pass: derive EUR ticker from base ticker by appending exchange suffixes
    # Prioritize XETRA (.DE) then Frankfurt (.F) as most liquid EUR markets
    if base_ticker:
        root = base_ticker.split('.')[0]
        for suffix in ('.DE', '.F', '.PA', '.MI', '.AS', '.BR', '.MC'):
            candidate = root + suffix
            try:
                price, currency = fetch_price_for_ticker(candidate)
                if currency == 'EUR':
                    print(f"  INFO {isin}: using derived ticker {candidate}")
                    return price
            except Exception:
                continue

    print(f"  SKIP {isin}: no EUR-quoted ticker found (base: {base_ticker})")
    return None

prices = {}
for isin in isins_to_fetch:
    try:
        # Check explicit override table first
        if isin in ISIN_TO_EUR_TICKER:
            override_ticker = ISIN_TO_EUR_TICKER[isin]
            price, currency = fetch_price_for_ticker(override_ticker)
            if price and currency == 'EUR':
                prices[isin] = price
                print(f"  OK {isin}: {price} EUR (override: {override_ticker})")
                continue
            print(f"  WARNING {isin}: override ticker {override_ticker} failed, falling back to auto-detect")

        price = fetch_eur_price(isin)
        if price is not None:
            prices[isin] = price
            print(f"  OK {isin}: {price} EUR")
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
