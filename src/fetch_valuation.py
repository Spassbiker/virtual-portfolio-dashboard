"""Deterministic valuation ratios (EV/EBITDA, PEG, ROE) from Yahoo Finance.

Ergänzt (nicht ersetzt) die LLM-recherchierten Fundamentaldaten in
fundamentalanalyse_ergebnisse.json um drei Kennzahlen, die Yahoo fertig
berechnet ausliefert — kein LLM-Aufruf, ein HTTP-Request je ISIN.

quoteSummary erfordert seit 2026 Cookie+Crumb (anonyme Requests -> 401).
Fehlt eine Kennzahl oder schlägt der Request fehl, bleibt das Feld None und
compute_funda_score wertet es neutral (kein erfundener Wert).
"""

import urllib.request
import http.cookiejar
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from paths import FUNDA as funda_path, load_json, save_json

HEADERS = {'User-Agent': 'Mozilla/5.0'}

_crumb_cache = {}


def _opener():
    if 'opener' not in _crumb_cache:
        cj = http.cookiejar.CookieJar()
        _crumb_cache['opener'] = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    return _crumb_cache['opener']


def _crumb():
    if 'crumb' in _crumb_cache:
        return _crumb_cache['crumb']
    opener = _opener()
    try:
        opener.open(urllib.request.Request('https://fc.yahoo.com', headers=HEADERS), timeout=10)
    except Exception:
        pass  # Cookie-Warmup kann 404 liefern, das Cookie wird trotzdem gesetzt.
    try:
        crumb = opener.open(
            urllib.request.Request('https://query1.finance.yahoo.com/v1/test/getcrumb', headers=HEADERS),
            timeout=10,
        ).read().decode().strip()
    except Exception:
        crumb = None
    _crumb_cache['crumb'] = crumb
    return crumb


def fetch_valuation(ticker):
    """Returns dict with ev_ebitda/peg_ratio/roe (None if unavailable)."""
    crumb = _crumb()
    if not crumb:
        return {}
    url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
           f"?modules=defaultKeyStatistics,financialData&crumb={crumb}")
    try:
        data = json.loads(_opener().open(urllib.request.Request(url, headers=HEADERS), timeout=15).read())
        result = data['quoteSummary']['result'][0]
    except Exception:
        return {}
    dks = result.get('defaultKeyStatistics', {}) or {}
    fd = result.get('financialData', {}) or {}
    out = {}
    ev_ebitda = dks.get('enterpriseToEbitda', {}).get('raw')
    if ev_ebitda is not None:
        out['ev_ebitda'] = round(ev_ebitda, 2)
    peg = dks.get('pegRatio', {}).get('raw')
    if peg is not None:
        out['peg_ratio'] = round(peg, 2)
    roe = fd.get('returnOnEquity', {}).get('raw')
    if roe is not None:
        out['roe'] = round(roe * 100, 2)  # als Prozent, konsistent mit gewinnwachstum_yoy etc.
    return out


def process_item(item):
    isin = item.get('isin')
    name = item.get('wertpapier', isin)
    if not isin:
        return False, 'no isin'
    candidates = ticker_map.candidates(isin) or ([ticker_map.USD_TICKER[isin]] if isin in ticker_map.USD_TICKER else [])
    if not candidates:
        return False, 'kein Ticker auflösbar'
    for ticker in candidates:
        vals = fetch_valuation(ticker)
        if vals:
            item.update(vals)
            item['valuation_source'] = f'yahoo:{ticker}'
            return True, f'ticker={ticker}, {vals}'
    return False, f'keine Valuation-Daten ({candidates[0]})'


def main():
    funda_data = load_json(funda_path, {})
    ok, fail = 0, 0
    for sector, items in funda_data.get('sektoren', {}).items():
        for item in items:
            success, detail = process_item(item)
            name = item.get('wertpapier', item.get('isin', '?'))
            if success:
                ok += 1
                print(f"  OK  {name}: {detail}")
            else:
                fail += 1
                print(f"  !!  {name}: {detail}")
    save_json(funda_path, funda_data)
    print(f"\nDone. {ok} updated, {fail} skipped/failed.")


if __name__ == '__main__':
    main()
