import json
import os
import urllib.request

base_dir = "/home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data"
depot_path = os.path.join(base_dir, "depot_status.json")

with open(depot_path, "r") as f:
    data = json.load(f)

depot = data.get("depot", {})
positions = depot.get("positionen", [])

isin_to_ticker = {
    'IT0003856405': 'LDO.MI', 'DE000ENER6Y0': 'ENR.DE', 'GB00B63H8491': 'RRU.DE',
    'FR0000121329': 'HO.PA', 'NL0010273215': 'ASML.AS', 'DE000A0D9PT0': 'MTX.DE',
    'DE0007030009': 'RHM.DE', 'DE0007164600': 'SAP.DE', 'FR0000073272': 'SAF.PA',
    'DE000ENAG999': 'EOAN.DE', 'DE0007037129': 'RWE.DE', 'DE0006231004': 'IFX.DE',
    'NL0000235190': 'AIR.PA', 'US72703X1063': '85H1.DE', 'DE0006095003': 'ECV.DE',
    'FR0010221234': 'ETL.PA'
}

def get_live_price(isin):
    if isin not in isin_to_ticker: return None
    ticker = isin_to_ticker[isin]
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            jdata = json.loads(response.read().decode())
            return float(jdata['chart']['result'][0]['meta']['regularMarketPrice'])
    except Exception as e:
        print(f"Failed to fetch {isin}: {e}")
        return None

portfoliowert = 0.0

for p in positions:
    isin = p.get("isin")
    if isin:
        price = get_live_price(isin)
        if price is not None:
            p["boersenkurs"] = round(price, 3)
            p["boersenwert"] = round(p["stueck"] * p["boersenkurs"], 2)
            p["gewinn_verlust"] = round(p["boersenwert"] - p["investiert"], 2)
    portfoliowert += p.get("boersenwert", 0.0)

depot["portfoliowert"] = round(portfoliowert, 2)
depot["gesamtvermoegen"] = round(depot["portfoliowert"] + depot["aktueller_barbestand"], 2)
data["depot"] = depot

with open(depot_path, "w") as f:
    json.dump(data, f, indent=2)

print(f"Updated portfoliowert: {depot['portfoliowert']}")
print(f"Updated gesamtvermoegen: {depot['gesamtvermoegen']}")
