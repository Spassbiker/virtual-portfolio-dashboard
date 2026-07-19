"""Single source of truth for ISIN -> EUR-ticker resolution.

Motivation (2026-07-08): update_prices.py, compute_indicators.py and
update_depot.py each carried their own, partly contradictory ISIN->ticker
tables. That produced wrong prices (US tickers priced in USD but treated as
EUR, e.g. Gilat GILT=12.36 USD) and price/SMA mismatches from wrong
instruments (SMA 174 vs. price 12). This module unifies resolution.

Rules:
  * European ISINs auto-resolve via their native EUR exchange (Yahoo search).
  * US/IL/other non-EUR home ISINs REQUIRE either an explicit, verified EUR
    ticker (ISIN_TO_EUR_TICKER) or a verified USD ticker (USD_TICKER) that is
    then converted to EUR via the live USD->EUR rate. Without either they are
    skipped — never guessed — so we don't price a wrong instrument.
  * plausible() guards against wrong-instrument data (price vs. its own SMA50).
  * eur_price()/eur_history() are the entry points: they return EUR values
    regardless of whether the source listing is in EUR or USD.
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

    # ETF-Sleeve (2026-07-11): Yahoo-Suche findet für diese Ireland-domizilierten
    # UCITS-ETFs keinen passenden EUR-Kandidaten (nur GBP/USD-Primärlistings) -
    # explizit auf verifizierte Xetra-EUR-Ticker gemappt.
    'IE00BYZK4552': '2B76.DE',   # iShares Automation & Robotics
    'IE000NDWFGA5': 'URNU.DE',   # Global X Uranium
    'IE00BP3QZ601': 'IS3Q.DE',   # iShares Edge MSCI World Quality Factor
    'IE00BMC38736': 'VVSM.DE',   # VanEck Semiconductor
    'IE000CK5G8J7': 'CBUX.DE',   # iShares Global Infrastructure
    'IE00B1XNHC34': 'IQQH.DE',   # iShares Global Clean Energy Transition
    'IE00BYPLS672': 'USPY.DE',   # L&G Cyber Security
    'IE000YU9K6K2': 'JEDI.DE',   # VanEck Space Innovators
}

# USD-Ticker für Namen ohne verlässliches EUR-Listing — werden über den
# Live-USD->EUR-Kurs umgerechnet und bleiben so im handelbaren Universum.
# Alle 2026-07-08 auf Yahoo als USD/EQUITY verifiziert.
USD_TICKER = {
    'IL0010825102': 'GILT',   # Gilat Satellite
    'US75513E1010': 'RTX',    # Raytheon (RTX Corp)
    'US6668071029': 'NOC',    # Northrop Grumman
    'US4586221056': 'LHX',    # L3Harris (Ticker LHX, nicht mehr LLL)
    'US65339F1012': 'NEE',    # NextEra Energy
    'US88033G4073': 'TER',    # Teradyne
    'US58551A1060': 'MELI',   # MercadoLibre
    'US3695501086': 'GD',     # General Dynamics
    'US7731221062': 'RKLB',   # Rocket Lab
    'US46269C1027': 'IRDM',   # Iridium
    'US79466L3024': 'CRM',    # Salesforce
    'US68389X1054': 'ORCL',   # Oracle
    'US4282911084': 'HXL',    # Hexcel
}

# ISINs mit weder EUR- noch verlässlichem USD-Listing — komplett überspringen.
NO_EUR_LISTING = {
    'US3696043013',  # unklare Zuordnung (war fälschlich GDX.DE = Gold-ETF)
    'US57778K1051',  # Maxar (übernommen/delisted)
    'US0003611052',  # US-Platzhalter ohne verlässliches Listing
}


def _http(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def is_skipped(isin):
    """True if this ISIN can't be priced at all (neither EUR nor USD listing)."""
    if not isin:
        return True
    if isin in ISIN_TO_EUR_TICKER or isin in USD_TICKER:
        return False
    if isin in NO_EUR_LISTING:
        return True
    # US/other non-EUR home without an explicit verified EUR/USD ticker -> skip.
    if isin[:2] in NON_EUR_PREFIXES:
        return True
    return False


def candidates(isin):
    """Ordered list of EUR ticker candidates to try; [] if none / USD-only."""
    if is_skipped(isin):
        return []
    if isin in ISIN_TO_EUR_TICKER:
        return [ISIN_TO_EUR_TICKER[isin]]
    # Reine USD-Namen haben kein EUR-Listing -> kein EUR-Kandidat (USD-Pfad greift).
    if isin in USD_TICKER:
        return []
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


_fx_cache = {}


def usd_to_eur_rate():
    """Live USD->EUR rate (EUR per 1 USD), cached per process. None if unavailable."""
    if 'usd_eur' in _fx_cache:
        return _fx_cache['usd_eur']
    rate = None
    try:
        data = _http("https://query1.finance.yahoo.com/v8/finance/chart/"
                     "USDEUR=X?interval=1d&range=1d")
        r = data['chart']['result'][0]['meta'].get('regularMarketPrice')
        if r and 0.5 < r < 1.5:   # Sanity: EUR/USD liegt realistisch um ~0.9
            rate = round(r, 5)
    except Exception:
        rate = None
    _fx_cache['usd_eur'] = rate
    return rate


def fetch_history(ticker, rng="1y"):
    """Return (closes, currency, meta) for a ticker; closes oldest-first, no None."""
    try:
        data = _http(f"https://query1.finance.yahoo.com/v8/finance/chart/"
                     f"{ticker}?interval=1d&range={rng}")
        result = data['chart']['result'][0]
        meta = result['meta']
        if meta.get('instrumentType') not in VALID_INSTRUMENT_TYPES:
            return None, None, None
        quote = result.get('indicators', {}).get('quote', [{}])[0]
        closes = [c for c in quote.get('close', []) if c is not None]
        return closes, meta.get('currency', ''), meta
    except Exception:
        return None, None, None


def fetch_index(symbol, rng="1y"):
    """(price, closes) für einen Index wie ^GDAXI. Ohne instrumentType-Guard,
    da Indizes weder EQUITY noch ETF sind. closes oldest-first, ohne None.
    Rückgabe (None, None) bei Fehler."""
    try:
        sym = symbol.replace("^", "%5E")
        data = _http(f"https://query1.finance.yahoo.com/v8/finance/chart/"
                     f"{sym}?interval=1d&range={rng}")
        result = data['chart']['result'][0]
        meta = result['meta']
        price = meta.get('regularMarketPrice')
        quote = result.get('indicators', {}).get('quote', [{}])[0]
        closes = [c for c in quote.get('close', []) if c is not None]
        return price, closes
    except Exception:
        return None, None


def eur_price(isin):
    """EUR spot price for an ISIN. Returns (price_eur, source) or (None, None).

    Tries an EUR listing first; falls back to the USD listing converted via the
    live USD->EUR rate.
    """
    for cand in candidates(isin):
        price, cur = fetch_price(cand)
        if price is not None and cur == 'EUR':
            return price, cand
    usd_t = USD_TICKER.get(isin)
    if usd_t:
        price, cur = fetch_price(usd_t)
        rate = usd_to_eur_rate()
        if price is not None and cur == 'USD' and rate:
            return round(price * rate, 3), f"{usd_t}·USD→EUR"
    return None, None


def eur_history(isin, rng="1y"):
    """EUR daily closes + latest for an ISIN. Returns (closes, latest, source).

    USD listings are converted with the current USD->EUR rate. A constant FX
    factor leaves trend/SMA/RSI relationships intact and yields EUR-denominated
    levels for display and valuation.
    """
    for cand in candidates(isin):
        closes, cur, meta = fetch_history(cand, rng=rng)
        if cur == 'EUR' and closes and meta and meta.get('regularMarketPrice'):
            return closes, meta['regularMarketPrice'], cand
    usd_t = USD_TICKER.get(isin)
    if usd_t:
        closes, cur, meta = fetch_history(usd_t, rng=rng)
        rate = usd_to_eur_rate()
        if cur == 'USD' and closes and meta and meta.get('regularMarketPrice') and rate:
            closes_eur = [round(c * rate, 4) for c in closes]
            latest_eur = round(meta['regularMarketPrice'] * rate, 4)
            return closes_eur, latest_eur, f"{usd_t}·USD→EUR"
    return None, None, None
