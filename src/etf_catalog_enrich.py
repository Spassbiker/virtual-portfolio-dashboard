"""One-time enrichment of etf_katalog.json with TER/AUM/Replikation/Ausschuettung,
plus correction of 3 name mismatches discovered 2026-07-11 (ISIN vs. actual fund
identity verified against Yahoo Finance search + justETF).

TER/AUM come from justETF (fetched manually via web_fetch, no reliable
programmatic API available from this host — Yahoo's quoteSummary needs a
crumb that gets 401'd from this IP, and justETF has no public JSON API).
This is NOT wired into the nightly cron; re-run by hand every ~3 months
when TER/AUM materially drift (rare for UCITS ETFs).
"""

import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import (
    ETF_KATALOG as etf_katalog_path,
    DEPOT as depot_path,
    CHART as chart_path,
    ETF_NEWS as etf_news_path,
    load_json,
    save_json,
)

STAND = datetime.date.today().isoformat()

# Verified 2026-07-11 via justETF (ISIN-keyed profile lookup).
STRUCTURE = {
    'IE00BM67HN09': dict(ter=0.25, aum_mio_eur=793,  replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00B1XNHC34': dict(ter=0.65, aum_mio_eur=2989, replikation='Physisch', ausschuettung='Ausschuettend'),
    'IE000NDWFGA5': dict(ter=0.65, aum_mio_eur=535,  replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00BM67HS53': dict(ter=0.25, aum_mio_eur=641,  replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00BL25JP72': dict(ter=0.25, aum_mio_eur=1930, replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE0002Y8CX98': dict(ter=0.40, aum_mio_eur=4400, replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE000YYE6WK5': dict(ter=0.55, aum_mio_eur=6345, replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE000OJ5TQP4': dict(ter=0.49, aum_mio_eur=2777, replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00BP3QZ601': dict(ter=0.25, aum_mio_eur=4943, replikation='Sampling', ausschuettung='Thesaurierend'),
    'IE00B4LN9N13': dict(ter=0.15, aum_mio_eur=700,  replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00BM67HV82': dict(ter=0.25, aum_mio_eur=931,  replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE000YU9K6K2': dict(ter=0.55, aum_mio_eur=1756, replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00BYPLS672': dict(ter=0.69, aum_mio_eur=3191, replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00BYVQ9F29': dict(ter=0.33, aum_mio_eur=1618, replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00BYZK4552': dict(ter=0.40, aum_mio_eur=4142, replikation='Sampling', ausschuettung='Thesaurierend'),
    'IE000CK5G8J7': dict(ter=0.65, aum_mio_eur=153,  replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00BM67HT60': dict(ter=0.25, aum_mio_eur=5412, replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00BMC38736': dict(ter=0.35, aum_mio_eur=7710, replikation='Physisch', ausschuettung='Thesaurierend'),
    'DE000A0H08H3': dict(ter=0.46, aum_mio_eur=318,  replikation='Physisch', ausschuettung='Ausschuettend'),
    'IE00BM67HQ30': dict(ter=0.25, aum_mio_eur=848,  replikation='Physisch', ausschuettung='Thesaurierend'),
    'IE00BL25JN58': dict(ter=0.25, aum_mio_eur=1092, replikation='Physisch', ausschuettung='Thesaurierend'),
    'LU1834988864': dict(ter=0.30, aum_mio_eur=214,  replikation='Synthetisch', ausschuettung='Thesaurierend'),
}

# ISIN -> (korrekter Name, korrektes Thema fuer News/Sentiment) fuer 2026-07-11
# entdeckte Fehlzuordnungen. Ticker war in allen 3 Faellen bereits korrekt;
# nur 'wertpapier'/'name' und implizit die Sektor-Story waren falsch.
NAME_FIXES = {
    'IE00BM67HN09': ('Xtrackers MSCI World Consumer Staples UCITS ETF 1C', 'consumer staples'),
    'DE000A0H08H3': ('iShares STOXX Europe 600 Food & Beverage UCITS ETF (DE)', 'food & beverage'),
    'IE00BYVQ9F29': ('iShares Nasdaq 100 UCITS ETF EUR Hedged Acc', 'nasdaq 100 tech'),
}


def fix_name_fields(data, key='sektoren'):
    changed = 0
    for sector, items in data.get(key, {}).items():
        for item in items:
            isin = item.get('isin')
            if isin in NAME_FIXES:
                new_name, _ = NAME_FIXES[isin]
                if item.get('wertpapier') != new_name:
                    item['wertpapier'] = new_name
                    changed += 1
    return changed


def main():
    # 1) etf_katalog.json: Namen korrigieren + TER/AUM/Struktur eintragen
    katalog = load_json(etf_katalog_path, {})
    n = fix_name_fields(katalog)
    enriched = 0
    for sector, items in katalog.get('sektoren', {}).items():
        for item in items:
            isin = item.get('isin')
            s = STRUCTURE.get(isin)
            if s:
                item.update(s)
                item['struktur_stand'] = STAND
                enriched += 1
    save_json(etf_katalog_path, katalog)
    print(f"etf_katalog.json: {n} Namen korrigiert, {enriched} Positionen mit TER/AUM angereichert")

    # 2) depot_status.json (etf_depot): nur Namen korrigieren, Positionen unangetastet
    depot = load_json(depot_path, {})
    depot_changed = 0
    for p in depot.get('etf_depot', {}).get('positionen', []):
        isin = p.get('isin')
        if isin in NAME_FIXES:
            new_name, _ = NAME_FIXES[isin]
            if p.get('wertpapier') != new_name:
                p['wertpapier'] = new_name
                depot_changed += 1
    if depot_changed:
        save_json(depot_path, depot)
    print(f"depot_status.json: {depot_changed} Positionsnamen korrigiert")

    # 3) chartanalyse_ergebnisse.json: falls dort ebenfalls gelistet
    chart = load_json(chart_path, {})
    if chart:
        c = fix_name_fields(chart)
        if c:
            save_json(chart_path, chart)
        print(f"chartanalyse_ergebnisse.json: {c} Namen korrigiert")

    # 4) etf_news_raw.json: name/thema korrigieren, damit kuenftige
    #    News-/Sentiment-Refreshes das richtige Thema abfragen
    news = load_json(etf_news_path, {})
    news_changed = 0
    for isin, entry in news.get('items', {}).items():
        if isin in NAME_FIXES and isinstance(entry, dict):
            new_name, new_thema = NAME_FIXES[isin]
            if entry.get('name') != new_name or entry.get('thema') != new_thema:
                entry['name'] = new_name
                entry['thema'] = new_thema
                news_changed += 1
    if news_changed:
        save_json(etf_news_path, news)
    print(f"etf_news_raw.json: {news_changed} Eintraege korrigiert (Name+Thema, naechster Refresh holt passende News)")


if __name__ == '__main__':
    main()
