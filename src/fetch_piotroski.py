"""Piotroski F-Score (0-9) aus Yahoo fundamentals-timeseries.

9 Ja/Nein-Kriterien über Rentabilität, Verschuldung/Liquidität und Effizienz,
jeweils aktuelles vs. vorheriges Geschäftsjahr. Hoher F-Score (7-9) = solide,
sich verbessernde Bilanz; niedriger (0-2) = Warnsignal / Value-Falle.

Datenquelle ist bewusst der timeseries-Endpoint, nicht das alte
quoteSummary-Bilanzmodul — Yahoo hat dort Bilanz/Cashflow-Details entfernt
(nur noch endDate). Fehlt eine Kennzahl oder gibt es <2 Geschäftsjahre, bleibt
piotroski None und compute_funda_score wertet neutral.
"""

import urllib.request
import json
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from fetch_valuation import _opener, _crumb, HEADERS
from paths import FUNDA as funda_path, load_json, save_json

FIELDS = [
    'annualNetIncome', 'annualTotalRevenue', 'annualGrossProfit', 'annualTotalAssets',
    'annualCurrentAssets', 'annualCurrentLiabilities', 'annualLongTermDebt',
    'annualOperatingCashFlow', 'annualOrdinarySharesNumber',
]


def _series(ticker):
    """Returns {feldname: {asOfDate: value}} für die annual-Serien, {} bei Fehler."""
    crumb = _crumb()
    if not crumb:
        return {}
    p2 = int(time.time())
    p1 = p2 - 5 * 365 * 86400
    url = (f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{ticker}"
           f"?symbol={ticker}&type={','.join(FIELDS)}&period1={p1}&period2={p2}&crumb={crumb}")
    try:
        data = json.loads(_opener().open(urllib.request.Request(url, headers=HEADERS), timeout=15).read())
        results = data.get('timeseries', {}).get('result', [])
    except Exception:
        return {}
    out = {}
    for s in results:
        typ = (s.get('meta', {}).get('type') or [None])[0]
        if not typ:
            continue
        by_date = {}
        for v in s.get(typ, []) or []:
            if v and v.get('asOfDate') is not None:
                raw = (v.get('reportedValue') or {}).get('raw')
                if raw is not None:
                    by_date[v['asOfDate']] = raw
        if by_date:
            out[typ] = by_date
    return out


def _two_years(series):
    """(t, t_prev) als Dicts feld->wert für die zwei jüngsten gemeinsamen Jahre.
    None, wenn keine zwei gemeinsamen Stichtage über alle Pflichtfelder existieren."""
    common = None
    for field in FIELDS:
        dates = set((series.get(field) or {}).keys())
        common = dates if common is None else (common & dates)
    if not common or len(common) < 2:
        return None
    d_t, d_prev = sorted(common)[-1], sorted(common)[-2]
    t = {f: series[f][d_t] for f in FIELDS}
    prev = {f: series[f][d_prev] for f in FIELDS}
    return t, prev


def piotroski_score(series):
    """0-9, oder None bei unzureichenden Daten."""
    pair = _two_years(series)
    if not pair:
        return None
    t, p = pair

    def roa(x):
        return x['annualNetIncome'] / x['annualTotalAssets'] if x['annualTotalAssets'] else None

    def cr(x):
        return x['annualCurrentAssets'] / x['annualCurrentLiabilities'] if x['annualCurrentLiabilities'] else None

    def gm(x):
        return x['annualGrossProfit'] / x['annualTotalRevenue'] if x['annualTotalRevenue'] else None

    def turn(x):
        return x['annualTotalRevenue'] / x['annualTotalAssets'] if x['annualTotalAssets'] else None

    def lev(x):
        return x['annualLongTermDebt'] / x['annualTotalAssets'] if x['annualTotalAssets'] else None

    score = 0
    # Rentabilität (4)
    if t['annualNetIncome'] > 0:
        score += 1
    if t['annualOperatingCashFlow'] > 0:
        score += 1
    roa_t, roa_p = roa(t), roa(p)
    if roa_t is not None and roa_p is not None and roa_t > roa_p:
        score += 1
    if t['annualOperatingCashFlow'] > t['annualNetIncome']:
        score += 1
    # Verschuldung / Liquidität (3)
    lev_t, lev_p = lev(t), lev(p)
    if lev_t is not None and lev_p is not None and lev_t < lev_p:
        score += 1
    cr_t, cr_p = cr(t), cr(p)
    if cr_t is not None and cr_p is not None and cr_t > cr_p:
        score += 1
    if t['annualOrdinarySharesNumber'] <= p['annualOrdinarySharesNumber'] * 1.01:  # ~1% Toleranz
        score += 1
    # Effizienz (2)
    gm_t, gm_p = gm(t), gm(p)
    if gm_t is not None and gm_p is not None and gm_t > gm_p:
        score += 1
    turn_t, turn_p = turn(t), turn(p)
    if turn_t is not None and turn_p is not None and turn_t > turn_p:
        score += 1
    return score


def process_item(item):
    isin = item.get('isin')
    name = item.get('wertpapier', isin)
    if not isin:
        return False, 'no isin'
    candidates = ticker_map.candidates(isin) or ([ticker_map.USD_TICKER[isin]] if isin in ticker_map.USD_TICKER else [])
    if not candidates:
        return False, 'kein Ticker auflösbar'
    for ticker in candidates:
        series = _series(ticker)
        score = piotroski_score(series) if series else None
        if score is not None:
            item['piotroski'] = score
            item['piotroski_source'] = f'yahoo:{ticker}'
            return True, f'ticker={ticker}, F={score}'
    return False, f'keine Bilanzdaten ({candidates[0]})'


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
