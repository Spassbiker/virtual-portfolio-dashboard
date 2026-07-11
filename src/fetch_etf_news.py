"""Deterministischer News-Fetcher für die ETF-Sentiment-Stufe (Phase 1+2).

Analog zu fetch_news.py (Aktien), aber themen-/sektorbasiert statt firmenbasiert:
ein ETF hat keine eigenen "Schlagzeilen", also wird pro ETF eine Themen-Query
(aus etf_theme_map.ETF_THEMES) an Yahoo-Suche geschickt. Typ A (Themen-ETF,
z.B. Uranium) und Typ B (breiter Sektor-ETF, z.B. MSCI World Energy) nutzen
dieselbe Fetch-Logik, nur mit unterschiedlichen Queries. Typ C (Faktor-ETFs)
sind in ETF_THEMES bewusst nicht enthalten und werden übersprungen.

Design-Prinzip wie beim Aktien-Pendant: dieses Skript bewertet nichts, es
sammelt nur Text. Die Bewertung übernimmt der LLM-Schritt (etf_sentiment_refresh.sh).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from etf_theme_map import ETF_THEMES
from paths import ETF_KATALOG as etf_katalog_path, ETF_NEWS as out_path, load_json, save_json


def isin_to_name_map():
    names = {}
    data = load_json(etf_katalog_path, {})
    for _, items in data.get("sektoren", {}).items():
        for item in items:
            isin = item.get("isin")
            if isin and isin not in names:
                names[isin] = item.get("wertpapier", "")
    return names


def fetch_headlines(query, count=8):
    q = urllib.parse.quote(query)
    url = (f"https://query2.finance.yahoo.com/v1/finance/search"
           f"?q={q}&newsCount={count}&quotesCount=0")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        return [], str(e)
    out = []
    for n in data.get("news", []):
        ts = n.get("providerPublishTime")
        out.append({
            "title": n.get("title", ""),
            "publisher": n.get("publisher", ""),
            "published": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d") if ts else None,
            "link": n.get("link", ""),
        })
    return out, None


def _signature(headlines):
    """Fingerprint eines Treffer-Sets, um Yahoos generischen Trending-Fallback
    zu erkennen: bei zu schnell wiederholten oder unbekannten Queries liefert
    die Suche denselben generischen Feed statt eines Fehlers - inhaltlich
    wertlos. Wird als zweite Sicherung neben dem Query-Caching genutzt."""
    return tuple(sorted(h.get("title", "") for h in headlines))


def main():
    names = isin_to_name_map()

    # Mehrere ETFs teilen sich oft dasselbe Thema (z.B. beide Defense-ETFs
    # -> "defense"). Jede einzigartige Query nur EINMAL abfragen (mit kurzer
    # Pause dazwischen) statt pro ETF neu - wiederholte Anfragen kurz
    # hintereinander lieferten in der Praxis Yahoos generischen Fallback-Feed
    # statt echter Themen-Treffer.
    unique_themes = sorted({meta["thema"] for meta in ETF_THEMES.values()})
    by_theme = {}
    for i, thema in enumerate(unique_themes):
        if i:
            time.sleep(0.8)
        by_theme[thema] = fetch_headlines(thema)

    sig_counts = {}
    for headlines, _ in by_theme.values():
        if headlines:
            sig_counts[_signature(headlines)] = sig_counts.get(_signature(headlines), 0) + 1

    result = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "items": {}}
    ok, empty = 0, 0
    for isin, meta in ETF_THEMES.items():
        name = names.get(isin, meta["ticker"])
        headlines, err = by_theme[meta["thema"]]
        is_generic_fallback = headlines and sig_counts.get(_signature(headlines), 0) > 1
        if is_generic_fallback:
            headlines = []
        result["items"][isin] = {
            "name": name,
            "ticker": meta["ticker"],
            "typ": meta["typ"],
            "thema": meta["thema"],
            "headlines": headlines,
            "error": err,
        }
        if headlines:
            ok += 1
        else:
            empty += 1
        note = " [generischer Fallback verworfen]" if is_generic_fallback else ""
        print(f"  {isin} ({name}, Typ {meta['typ']}, thema={meta['thema']!r}): {len(headlines)} Treffer{note}"
              + (f" [!{err}]" if err else ""))

    save_json(out_path, result)
    print(f"\nDone. {ok} mit News, {empty} ohne. -> {out_path}")


if __name__ == "__main__":
    main()
