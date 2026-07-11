"""ETF-Empfehlungs-Ranking, analog zum Aktien-Ranking im Dashboard.

Composite-Score (0-100) aus vier Bloecken:
  - Momentum (35%):   Trendlage (Kurs vs. SMA50/SMA200), 12M-Return, RSI
  - Risiko (25%):     annualisierte Volatilitaet, Max-Drawdown 1J, Ertrag/Risiko
  - Sentiment (20%):  aus etf_sentiment_scores.json (KI-Themen-Einschaetzung)
  - Struktur (20%):   TER + Fondsgroesse (aus etf_katalog.json, siehe
                       etf_catalog_enrich.py fuer die Herkunft der Werte)

Bucket: CORE >=75, SATELLITE 60-74, BEOBACHTEN 45-59, MEIDEN <45.
Veto: AUM < 50 Mio. -> Bucket-Cap MEIDEN. TER > 1.0% -> -10 Punkte.
Grosser Drawdown (< -40%) + negatives Sentiment -> Bucket-Cap SATELLITE.

Peer-Rank: Platzierung innerhalb des jeweiligen Themen-Sektors aus dem Katalog.
"""

import os
import sys
import datetime
import statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from compute_indicators import sma, rsi
from paths import ETF_KATALOG as etf_katalog_path, ETF_SENT as etf_sent_path, ETF_RANKING as etf_ranking_path, load_json, save_json

WEIGHTS = {'momentum': 0.35, 'risiko': 0.25, 'sentiment': 0.20, 'struktur': 0.20}


def clip(v, lo, hi):
    return max(lo, min(hi, v))


def pct_return(closes, days_back):
    if len(closes) <= days_back:
        return None
    start = closes[-1 - days_back]
    if not start:
        return None
    return (closes[-1] / start - 1) * 100


def max_drawdown(closes):
    if len(closes) < 2:
        return None
    peak = closes[0]
    worst = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (c / peak - 1) * 100
        if dd < worst:
            worst = dd
    return round(worst, 2)


def annualized_vol(closes):
    if len(closes) < 20:
        return None
    rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes)) if closes[i - 1]]
    if len(rets) < 10:
        return None
    return round(statistics.pstdev(rets) * (252 ** 0.5) * 100, 2)


def momentum_score(closes, latest):
    values = closes + ([latest] if not closes or closes[-1] != latest else [])
    s50 = sma(values, 50)
    s200 = sma(values, 200)
    r = rsi(values, 14)
    ret12m = pct_return(closes, min(252, len(closes) - 1)) if len(closes) > 30 else None

    trend = 50.0
    if s50 and s200 and latest:
        if latest > s50 > s200:
            trend = 100.0
        elif latest < s50 < s200:
            trend = 0.0
        elif latest > s200:
            trend = 65.0
        else:
            trend = 35.0

    ret_score = 50.0 if ret12m is None else clip(50 + ret12m * (50 / 30), 0, 100)

    rsi_score = 50.0
    if r is not None:
        if r >= 75:
            rsi_score = clip(100 - (r - 75) * 4, 0, 60)
        elif r <= 30:
            rsi_score = clip(r / 30 * 40, 0, 40)
        else:
            rsi_score = clip(50 + (r - 50) * 1.2, 0, 100)

    parts = {'trend': round(trend, 1), 'return_12m': round(ret_score, 1), 'rsi': round(rsi_score, 1)}
    score = (trend + ret_score + rsi_score) / 3
    return round(score, 1), parts, ret12m, s50, s200, r


def risk_score(closes, ret12m):
    vol = annualized_vol(closes)
    dd = max_drawdown(closes)

    vol_score = 50.0 if vol is None else clip(100 - vol * 2.5, 0, 100)
    dd_score = 50.0 if dd is None else clip(100 + dd * 2.0, 0, 100)
    if ret12m is not None and vol:
        sharpe_ish = ret12m / vol
        sharpe_score = clip(50 + sharpe_ish * 40, 0, 100)
    else:
        sharpe_score = 50.0

    parts = {'volatilitaet': round(vol_score, 1), 'drawdown': round(dd_score, 1), 'ertrag_risiko': round(sharpe_score, 1)}
    score = (vol_score + dd_score + sharpe_score) / 3
    return round(score, 1), parts, vol, dd


def sentiment_score_for(isin, sentiment_data):
    entry = sentiment_data.get('scores', {}).get(isin)
    if not entry or not isinstance(entry.get('sentiment_score'), (int, float)):
        return 50.0, None
    raw = entry['sentiment_score']
    return round(clip(50 + raw * 10, 0, 100), 1), raw


def struktur_score(ter, aum_mio_eur):
    if ter is None:
        ter_score = 50.0
    elif ter <= 0.20:
        ter_score = 100.0
    elif ter <= 0.35:
        ter_score = 85.0
    elif ter <= 0.50:
        ter_score = 65.0
    elif ter <= 0.65:
        ter_score = 45.0
    else:
        ter_score = 25.0

    if aum_mio_eur is None:
        aum_score = 50.0
    elif aum_mio_eur >= 1000:
        aum_score = 100.0
    elif aum_mio_eur >= 500:
        aum_score = 85.0
    elif aum_mio_eur >= 200:
        aum_score = 65.0
    elif aum_mio_eur >= 50:
        aum_score = 45.0
    else:
        aum_score = 10.0

    parts = {'ter': round(ter_score, 1), 'aum': round(aum_score, 1)}
    score = (ter_score + aum_score) / 2
    return round(score, 1), parts


def bucket_for(composite, aum_mio_eur, ter, dd, sentiment_raw):
    if aum_mio_eur is not None and aum_mio_eur < 50:
        return 'MEIDEN', ['Fondsgroesse < 50 Mio. EUR (Schliessungsrisiko)']

    warnings = []
    cap = None
    if ter is not None and ter > 1.0:
        composite -= 10
        warnings.append('TER > 1.0% p.a.')
    if dd is not None and dd < -40 and sentiment_raw is not None and sentiment_raw < 0:
        cap = 74
        warnings.append('Drawdown > 40% bei negativem Sentiment')

    if cap is not None:
        composite = min(composite, cap)

    if composite >= 75:
        bucket = 'CORE'
    elif composite >= 60:
        bucket = 'SATELLITE'
    elif composite >= 45:
        bucket = 'BEOBACHTEN'
    else:
        bucket = 'MEIDEN'
    return bucket, warnings, composite


def compute_for_isin(isin, cache, sentiment_data, ter, aum_mio_eur):
    if isin in cache:
        return cache[isin]

    closes, latest, ticker = ticker_map.eur_history(isin)
    if not closes or not latest:
        cache[isin] = None
        return None

    mom, mom_parts, ret12m, s50, s200, r = momentum_score(closes, latest)
    risk, risk_parts, vol, dd = risk_score(closes, ret12m)
    sent, sent_raw = sentiment_score_for(isin, sentiment_data)
    struk, struk_parts = struktur_score(ter, aum_mio_eur)

    composite = (
        WEIGHTS['momentum'] * mom
        + WEIGHTS['risiko'] * risk
        + WEIGHTS['sentiment'] * sent
        + WEIGHTS['struktur'] * struk
    )

    bucket, warnings, composite_adj = bucket_for(composite, aum_mio_eur, ter, dd, sent_raw)

    result = {
        'isin': isin,
        'ticker': ticker,
        'aktueller_kurs': latest,
        'composite': round(composite_adj, 1),
        'bucket': bucket,
        'warnings': warnings,
        'momentum': {'score': mom, 'parts': mom_parts, 'return_12m_pct': round(ret12m, 1) if ret12m is not None else None,
                     'sma_50': s50, 'sma_200': s200, 'rsi_14': r},
        'risiko': {'score': risk, 'parts': risk_parts, 'volatilitaet_pct': vol, 'max_drawdown_pct': dd},
        'sentiment': {'score': sent, 'raw': sent_raw},
        'struktur': {'score': struk, 'parts': struk_parts, 'ter': ter, 'aum_mio_eur': aum_mio_eur},
    }
    cache[isin] = result
    return result


def main():
    katalog = load_json(etf_katalog_path, {})
    sentiment_data = load_json(etf_sent_path, {'scores': {}})

    cache = {}
    out_sektoren = {}
    ok, fail = 0, 0

    for sector, items in katalog.get('sektoren', {}).items():
        rows = []
        for item in items:
            isin = item.get('isin')
            if not isin:
                continue
            result = compute_for_isin(isin, cache, sentiment_data, item.get('ter'), item.get('aum_mio_eur'))
            if result is None:
                fail += 1
                print(f"  !! {item.get('wertpapier', isin)}: kein Kurs auflösbar")
                continue
            ok += 1
            row = dict(result)
            row['wertpapier'] = item.get('wertpapier', isin)
            rows.append(row)

        rows.sort(key=lambda r: r['composite'], reverse=True)
        for i, row in enumerate(rows, start=1):
            row['peer_rank'] = i
            row['peer_total'] = len(rows)
        out_sektoren[sector] = rows

    out = {
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'gewichtung': WEIGHTS,
        'sektoren': out_sektoren,
    }
    save_json(etf_ranking_path, out)
    print(f"\nDone. {ok} ETFs bewertet, {fail} übersprungen (kein Kurs).")


if __name__ == '__main__':
    main()
