"""Deterministic news fetcher for the sentiment stage (Stufe 1 + 2).

Pulls recent headlines per relevant ISIN from Yahoo Finance's free search
endpoint (no API key) and writes them to data/news_raw.json. This file is the
*input* for the LLM sentiment stage: the Portfoliomanager-Agent (cron) reads the
raw headlines and produces data/sentiment_scores.json.

Design principle: this script does NO judgement. It only collects text. All
qualitative evaluation happens in the LLM step so nothing here can hallucinate.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from paths import DEPOT as depot_path, CHART as chart_path, FUNDA as funda_path, NEWS as out_path, load_json, save_json

# Ticker display/fallback comes from the shared source of truth (ticker_map).
# No separate table here anymore — that divergence caused wrong/stale tickers.
isin_to_ticker = ticker_map.ISIN_TO_EUR_TICKER

# Legal-form / filler tokens that must NOT count as company keywords.
_STOP_TOKENS = {
    'the', 'and', 'für', 'ag', 'sa', 'se', 'nv', 'plc', 'spa', 'inc', 'corp',
    'corporation', 'ltd', 'co', 'holding', 'holdings', 'group', 'gruppe',
    'company', 'technologies', 'technology', 'international', 'systems',
    'aktiengesellschaft', 'adr', 'nsa', 'oyj',
}


def company_keywords(name, ticker):
    """Distinctive lowercase tokens that a relevant headline should contain."""
    kws = set()
    for tok in re.split(r"[^A-Za-zÀ-ÿ0-9]+", (name or "")):
        t = tok.lower().strip(".")
        if len(t) >= 3 and t not in _STOP_TOKENS:
            kws.add(t)
    root = (ticker or "").split(".")[0].lower()
    if len(root) >= 2:
        kws.add(root)
    return kws


def headline_relevant(title, keywords):
    """True if the headline mentions the company as a whole word (not a substring).

    Word-boundary matching avoids false hits like 'ses' inside 'businesses'.
    """
    if not keywords:
        return True  # no basis to filter -> keep (defensive)
    t = (title or "").lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", t) for kw in keywords)


def isin_to_name_map():
    names = {}
    for path in (chart_path, funda_path):
        data = load_json(path)
        if data is None:
            continue
        for _, items in data.get("sektoren", {}).items():
            for item in items:
                isin = item.get("isin")
                if isin and isin not in names:
                    names[isin] = item.get("wertpapier", "").replace(" (Teil 2)", "")
    return names


def relevant_isins():
    """Depot positions + current buy candidates (both Kaufen-empfohlen)."""
    isins = set()
    depot = load_json(depot_path, {}).get("depot", {})
    for p in depot.get("positionen", []):
        if p.get("isin"):
            isins.add(p["isin"])
    chart = load_json(chart_path, {})
    funda = load_json(funda_path, {})
    chart_buys = {i["isin"] for _, its in chart.get("sektoren", {}).items()
                  for i in its if i.get("empfehlung", "").lower() == "kaufen" and i.get("isin")}
    funda_buys = {i["isin"] for _, its in funda.get("sektoren", {}).items()
                  for i in its if (i.get("empfehlung") or "").lower() == "kaufen" and i.get("isin")}
    isins |= (chart_buys & funda_buys)
    return sorted(isins)


def fetch_headlines(query, count=6):
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


def main():
    names = isin_to_name_map()
    isins = relevant_isins()
    result = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "items": {}}
    ok, empty = 0, 0
    for isin in isins:
        name = names.get(isin, "")
        ticker = isin_to_ticker.get(isin, "")
        # Company name gives better-targeted headlines than the ticker.
        query = name or ticker or isin
        raw, err = fetch_headlines(query)

        # Relevance filter: drop Yahoo's generic-feed noise so the sentiment
        # stage only sees company-specific headlines (or an honest empty list).
        kws = company_keywords(name, ticker)
        headlines = [h for h in raw if headline_relevant(h.get("title", ""), kws)]
        # If the name query returned only noise, retry once with the ticker —
        # sometimes the ticker query hits the right company feed.
        if not headlines and ticker:
            raw2, err2 = fetch_headlines(ticker)
            hl2 = [h for h in raw2 if headline_relevant(h.get("title", ""), kws)]
            if hl2:
                headlines, err = hl2, err2
                raw = raw2
        dropped = len(raw) - len(headlines)

        result["items"][isin] = {
            "name": name,
            "ticker": ticker,
            "headlines": headlines,
            "error": err,
        }
        if headlines:
            ok += 1
        else:
            empty += 1
        print(f"  {isin} ({name or ticker}): {len(headlines)} relevant"
              + (f", {dropped} Rausch verworfen" if dropped else "")
              + (f" [!{err}]" if err else ""))

    save_json(out_path, result)
    print(f"\nDone. {ok} mit News, {empty} ohne. -> {out_path}")


if __name__ == "__main__":
    main()
