"""Deterministic technical indicators from Yahoo Finance history.

Replaces the LLM-hallucinated SMA/RSI/MACD/Support/Resistance fields in
chartanalyse_ergebnisse.json with real values computed from a 1-year daily
history. Original values are preserved with `legacy_` prefix so nothing is lost
if the Yahoo lookup fails or returns something odd.

Trend and signal fields are LEFT AS-IS — those are LLM narrative and the daily
manager cron can rewrite them on top of the fresh numbers.
"""

import urllib.request
import json
import os
import math
import datetime
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from paths import CHART as chart_path, load_json, save_json

VALID_INSTRUMENT_TYPES = ('EQUITY', 'ETF')

LEGACY_FIELDS = ('rsi_14', 'macd', 'sma_50', 'sma_200', 'unterstuetzung', 'widerstand', 'aktueller_kurs')


def http_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def resolve_eur_ticker(isin):
    """Candidate EUR tickers from the shared map ([] if the ISIN is skipped)."""
    return ticker_map.candidates(isin)


def fetch_history(ticker):
    """Returns (closes, currency, meta) — closes is a list of daily closes,
    oldest first, with None removed. meta.regularMarketPrice is the latest."""
    data = http_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1d&range=1y"
    )
    result = data['chart']['result'][0]
    meta = result['meta']
    if meta.get('instrumentType') not in VALID_INSTRUMENT_TYPES:
        return None, None, None
    if meta.get('currency') != 'EUR':
        return None, meta.get('currency'), None
    indicators = result.get('indicators', {}).get('quote', [{}])[0]
    closes_raw = indicators.get('close', [])
    closes = [c for c in closes_raw if c is not None]
    return closes, 'EUR', meta


def sma(values, window):
    if len(values) < window:
        return None
    return round(sum(values[-window:]) / window, 3)


def rsi(values, period=14):
    """Wilder's smoothed RSI."""
    if len(values) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        if change > 0:
            gains += change
        else:
            losses -= change
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        gain = change if change > 0 else 0.0
        loss = -change if change < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def ema(values, period):
    """EMA series (same length as values, first `period-1` entries are seed)."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    out = [None] * (period - 1) + [ema_val]
    for v in values[period:]:
        ema_val = v * k + ema_val * (1 - k)
        out.append(ema_val)
    return out


def macd_label(values):
    """Returns 'Positiv' / 'Negativ' / 'Neutral' based on MACD line vs. signal.

    MACD = EMA(12) - EMA(26); signal = EMA(9) of MACD.
    'Neutral' if the two are within 0.5% of the last close (noise band).
    """
    if len(values) < 35:
        return None
    ema12 = ema(values, 12)
    ema26 = ema(values, 26)
    macd_line = [
        (a - b) if a is not None and b is not None else None
        for a, b in zip(ema12, ema26)
    ]
    macd_clean = [m for m in macd_line if m is not None]
    if len(macd_clean) < 10:
        return None
    signal_line = ema(macd_clean, 9)
    if not signal_line or signal_line[-1] is None:
        return None
    diff = macd_clean[-1] - signal_line[-1]
    noise = abs(values[-1]) * 0.005
    if diff > noise:
        return 'Positiv'
    if diff < -noise:
        return 'Negativ'
    return 'Neutral'


def support_resistance(values, window=60):
    """Support = min of last `window` closes; resistance = max."""
    tail = values[-window:] if len(values) >= window else values
    if not tail:
        return None, None
    return round(min(tail), 2), round(max(tail), 2)


def momentum_12_1(values):
    """Academic 12-1 momentum: return from t-252 to t-21 (skips the most
    recent month to avoid short-term reversal effects). None if history is
    too short (~1y needed)."""
    if len(values) < 252:
        return None
    p_start = values[-252]
    p_recent = values[-21]
    if not p_start:
        return None
    return round((p_recent / p_start - 1) * 100, 2)


def compute_all(closes, latest_price):
    """closes must be at least ~35 long for full output; missing indicators -> None."""
    values = closes + ([latest_price] if latest_price and (not closes or closes[-1] != latest_price) else [])
    return {
        'aktueller_kurs': round(latest_price, 3) if latest_price else None,
        'sma_50': sma(values, 50),
        'sma_200': sma(values, 200),
        'rsi_14': rsi(values, 14),
        'macd': macd_label(values),
        'unterstuetzung': support_resistance(values)[0],
        'widerstand': support_resistance(values)[1],
        'momentum_12_1': momentum_12_1(values),
    }


def process_position(item):
    isin = item.get('isin')
    name = item.get('wertpapier', isin)
    if not isin:
        return False, 'no isin'
    # EUR-Historie über die gemeinsame Quelle (inkl. USD->EUR-Umrechnung).
    closes, latest, ticker = ticker_map.eur_history(isin)
    if not closes or not latest:
        return False, 'kein EUR-/USD-Kurs auflösbar'
    indicators = compute_all(closes, latest)

    # Plausibility guard: reject wrong-instrument data (price wildly off its own
    # SMA50) so a bad ticker never poisons the recommendation engine.
    if not ticker_map.plausible(latest, indicators.get('sma_50')):
        return False, (f'IMPLAUSIBEL verworfen ({ticker}): Kurs {latest} vs. '
                       f"SMA50 {indicators.get('sma_50')} — vermutlich falsches Instrument")

    # Preserve original values under legacy_ prefix (only once, if not already saved).
    for field in LEGACY_FIELDS:
        legacy_key = f'legacy_{field}'
        if field in item and legacy_key not in item:
            item[legacy_key] = item[field]

    # Overwrite with deterministic values (skip None to keep old value if calc failed).
    for field, value in indicators.items():
        if value is not None:
            item[field] = value

    item['indicators_computed_at'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    item['indicators_source'] = f'yahoo:{ticker}'
    return True, f'ticker={ticker}, price={latest}, closes={len(closes)}'


def main():
    chart_data = load_json(chart_path, {})

    ok, fail = 0, 0
    for sector, items in chart_data.get('sektoren', {}).items():
        for item in items:
            success, detail = process_position(item)
            name = item.get('wertpapier', item.get('isin', '?'))
            if success:
                ok += 1
                print(f"  OK  {name}: {detail}")
            else:
                fail += 1
                print(f"  !!  {name}: {detail}")

    save_json(chart_path, chart_data)

    print(f"\nDone. {ok} updated, {fail} skipped/failed.")


if __name__ == '__main__':
    main()
