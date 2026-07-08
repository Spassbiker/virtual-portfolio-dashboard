"""Single source of truth for ISIN -> EUR-ticker resolution.

Motivation (2026-07-08): update_prices.py, compute_indicators.py and
update_depot.py each carried their own, partly contradictory ISIN->ticker
tables. That produced wrong prices (US tickers priced in USD but treated as
EUR, e.g. Gilat GILT=12.36 USD) and price/SMA mismatches from wrong
instruments (SMA 174 vs. price 12). This module unifies resolution.

Rules:
  * European ISINs auto-resolve via their native EUR exchange (Yahoo search).
  * US/IL/other non-EUR home ISINs REQUIRE an explicit, verified EUR ticker
    (see ISIN_TO_EUR_TICKER). Without one they are skipped — never guessed —
    so we don't accidentally price a USD listing or a wrong instrument.
  * plausible() guards against wrong-instrument data (price vs. its own SMA50).
"""

import urllib.request
import json

EUR_SUFFIXES = ('.DE', '.F', '.MI', '.PA', '.AS', '.BR', '.LS', '.MC',
                '.VI', '.HE', '.CO', '.OL', '.ST', '.IR')

VALID_INSTRUMENT_TYPES = ('EQUITY', 'ETF')

# Non-EUR home countries: an ISIN with these prefixes needs an explicit,
# verified EUR ticker below, otherwise it is skipped.
NON_EUR_PREFIXES = ('US', 'IL', 'CA', 'KY', 'BM', 'CN', 'HK', 'JP', 'KR', 'CH', 'GB')

# Verified-correct EUR tickers (price sanity-checked on Yahoo, 2026-07-08).
# Only add entries you have confirmed return currency=EUR AND a plausible price.
ISIN_TO_EUR_TICKER = {
    'US67066G1040': 'NVD.DE',    # Nvidia (XETRA NVD; NVDA is a fund)
    'US5949181045': 'MSF.DE',    # Microsoft
    'US02079K3059': 'ABEA.DE',   # Alphabet A
    'US02079K1079': 'ABEC.DE',   # Alphabet C
    'US88160R1014': 'TL0.DE',    # Tesla (NOT TSLA.AS, that is a wrong instrument)
    'US30303M1027': 'FB2A.DE',   # Meta Platforms
    'US0970231058': 'BCO.DE',    # Boeing
    'US5398301094': 'LOM.DE',    # Lockheed Martin
    'GB0002634946': 'BSP.DE',    # BAE Systems (GB ISIN, XETRA EUR listing)
    'GB00B63H8491': 'RRU.DE',    # Rolls-Royce Holdings (XETRA EUR listing)
    'US72703X1063': '85H1.DE',   # Planet Labs (Frankfurt)
}

# ISINs with NO reliable EUR listing on Yahoo — skip entirely (never price,
# never recommend as a buy). Verified 2026-07-08: only USD listings or the
# apparent EUR tickers are wrong instruments (e.g. NEE.F=0.55, L3H.F=72).
NO_EUR_LISTING = {
    'IL0010825102',  # Gilat Satellite (nur NASDAQ USD)
    'US75513E1010',  # Raytheon / RTX
    'US6668071029',  # Northrop Grumman
    'US4586221056',  # L3Harris
    'US65339F1012',  # NextEra Energy
    'US88033G4073',  # Teradyne
    'US58551A1060',  # MercadoLibre
    'US3695501086',  # General Dynamics
    'US3696043013',  # (war fälschlich GDX.DE = Gold-Miners-ETF)
    'US57778K1051',  # Maxar
    'US7731221062',  # Rocket Lab
    'US46269C1027',  # Iridium
    'US79466L3024',  # Salesforce
    'US68389X1054',  # Oracle
    'US0003611052',  # (US-Platzhalter ohne verlässliches EUR-Listing)
    'US4282911084',  # Hexcel
}


def _http(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def is_skipped(isin):
    """True if this ISIN should never be priced/traded (no EUR listing)."""
    if not isin:
        return True
    if isin in ISIN_TO_EUR_TICKER:
        return False
    if isin in NO_EUR_LISTING:
        return True
    # US/other non-EUR home without an explicit verified EUR ticker -> skip.
    if isin[:2] in NON_EUR_PREFIXES:
        return True
    return False


def candidates(isin):
    """Ordered list of EUR ticker candidates to try; [] if the ISIN is skipped."""
    if is_skipped(isin):
        return []
    if isin in ISIN_TO_EUR_TICKER:
        return [ISIN_TO_EUR_TICKER[isin]]
    # European ISIN: resolve via Yahoo search, prefer EUR-suffixed symbols.
    try:
        data = _http(f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}")
    except Exception:
        return []
    quotes = data.get('quotes', [])
    out = []
    for q in quotes:
        sym = q.get('symbol', '')
        if sym and any(sym.endswith(s) for s in EUR_SUFFIXES):
            out.append(sym)
    base = quotes[0].get('symbol') if quotes else None
    if base and '.' in base:
        root = base.split('.')[0]
        for suf in ('.DE', '.F'):
            cand = root + suf
            if cand not in out:
                out.append(cand)
    return out


def plausible(price, sma50):
    """Guard against wrong-instrument data.

    A price is implausible if it differs from its own SMA50 by more than 3x in
    either direction — that only happens across different instruments, not from
    normal market moves. Returns True when there is no basis to reject.
    """
    if price is None or price <= 0:
        return False
    if not sma50 or sma50 <= 0:
        return True
    return sma50 / 3.0 <= price <= sma50 * 3.0


def fetch_price(ticker):
    """Return (price, currency) for a ticker, or (None, None) on error/wrong type."""
    try:
        data = _http(f"https://query1.finance.yahoo.com/v8/finance/chart/"
                     f"{ticker}?interval=1d&range=1d")
        meta = data['chart']['result'][0]['meta']
        if meta.get('instrumentType') not in VALID_INSTRUMENT_TYPES:
            return None, None
        return round(meta['regularMarketPrice'], 3), meta.get('currency', '')
    except Exception:
        return None, None
