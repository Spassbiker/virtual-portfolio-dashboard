"""Deterministic news fetcher for the sentiment stage (Stufe 1 + 2).

Pulls recent headlines per relevant ISIN from three free, key-less sources and
writes them to data/news_raw.json. This file is the *input* for the LLM
sentiment stage: the Portfoliomanager-Agent (cron) reads the raw headlines and
produces data/sentiment_scores.json.

Quellen (alle kostenlos, kein API-Key):
  1. EQS/DGAP-Ad-hoc (finanznachrichten.de RSS) — Pflichtmitteilungen mit
     ISIN-Tag, das kursrelevanteste Signal (Gewinnwarnung, Guidance, M&A).
     Wird EINMAL für alle ISINs geholt und dann verteilt.
  2. Google-News-RSS (deutschsprachig, pro Firma) — deutlich bessere Trefferquote
     für deutsche Nebenwerte als die alte Yahoo-only-Lösung.
  3. Yahoo Finance Search — Ergänzung/Fallback, vor allem für internationale Werte.

Design principle: this script does NO judgement. It only collects text. All
qualitative evaluation happens in the LLM step so nothing here can hallucinate.
Fällt eine Quelle aus (Timeout, Formatänderung), laufen die anderen weiter.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticker_map
from paths import DEPOT as depot_path, CHART as chart_path, FUNDA as funda_path, NEWS as out_path, load_json, save_json

# Ticker display/fallback comes from the shared source of truth (ticker_map).
# No separate table here anymore — that divergence caused wrong/stale tickers.
isin_to_ticker = ticker_map.ISIN_TO_EUR_TICKER

MAX_AGE_DAYS = 7        # nur Schlagzeilen der letzten N Tage
MAX_HEADLINES = 15      # pro ISIN, nach Merge/Dedup/Sortierung
ADHOC_FEED_URL = "https://www.finanznachrichten.de/rss-aktien-adhoc/"

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


def _parse_date(raw):
    """Best-effort Parse für RFC-2822 (Google/finanznachrichten pubDate) und
    ISO-8601 ('YYYY-MM-DDTHH:MM:SSZ'). Gibt timezone-aware datetime oder None."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _within_max_age(dt):
    if dt is None:
        return True  # kein Datum erkennbar -> defensiv behalten
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)


def _norm_title(title):
    """Normalisierter Titel für Dedup über Quellen hinweg (grobe Ähnlichkeit)."""
    t = re.sub(r"[^a-z0-9À-ÿ ]", "", (title or "").lower())
    return re.sub(r"\s+", " ", t).strip()[:80]


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


def fetch_adhoc_all(isins):
    """Holt den EQS/DGAP-Ad-hoc-Feed EINMAL und verteilt ihn per ISIN.

    Rückgabe: {isin: [headline, ...]}. Bei Fehlschlag: leere Listen (defensiv,
    die anderen Quellen laufen weiter).
    """
    result = {isin: [] for isin in isins}
    req = urllib.request.Request(ADHOC_FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except Exception as e:
        print(f"  [Ad-hoc-Feed] Fehler: {e}")
        return result
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  [Ad-hoc-Feed] Parse-Fehler: {e}")
        return result
    ns = {"fn": "http://www.finanznachrichten.de/service/rss"}
    for item in root.iter("item"):
        isin_el = item.find("fn:isin", ns)
        isin = (isin_el.text or "").strip() if isin_el is not None else ""
        if isin not in result:
            continue
        pub = item.findtext("pubDate", "")
        dt = _parse_date(pub)
        if not _within_max_age(dt):
            continue
        result[isin].append({
            "title": item.findtext("title", ""),
            "publisher": "EQS/DGAP Ad-hoc",
            "published": dt.strftime("%Y-%m-%d") if dt else None,
            "link": item.findtext("link", ""),
            "quelle": "adhoc",
        })
    return result


def fetch_google_news(query, count=10):
    # Keine Anführungszeichen (exakte Phrase): Abkürzungen in den Firmennamen
    # der Datenquelle (z.B. "Dt. Telekom" statt "Deutsche Telekom") würden
    # sonst 0 Treffer liefern, obwohl passende News existieren.
    q = urllib.parse.quote(f'{query} Aktie')
    url = f"https://news.google.com/rss/search?q={q}&hl=de&gl=DE&ceid=DE:de"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except Exception as e:
        return [], str(e)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return [], str(e)
    out = []
    for item in root.iter("item"):
        pub = item.findtext("pubDate", "")
        dt = _parse_date(pub)
        if not _within_max_age(dt):
            continue
        source_el = item.find("source")
        out.append({
            "title": item.findtext("title", ""),
            "publisher": (source_el.text if source_el is not None else "") or "",
            "published": dt.strftime("%Y-%m-%d") if dt else None,
            "link": item.findtext("link", ""),
            "quelle": "google_news",
        })
        if len(out) >= count:
            break
    return out, None


def fetch_yahoo_news(query, count=8):
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
        dt = datetime.fromtimestamp(ts, timezone.utc) if ts else None
        if not _within_max_age(dt):
            continue
        out.append({
            "title": n.get("title", ""),
            "publisher": n.get("publisher", ""),
            "published": dt.strftime("%Y-%m-%d") if dt else None,
            "link": n.get("link", ""),
            "quelle": "yahoo",
        })
    return out, None


def merge_headlines(adhoc, google, yahoo):
    """Ad-hoc zuerst (kursrelevanteste Pflichtmeldungen), dann nach Datum
    absteigend sortiert, über alle Quellen hinweg per Titel dedupliziert."""
    seen = set()
    merged = []
    for h in adhoc:
        key = _norm_title(h["title"])
        if key and key not in seen:
            seen.add(key)
            merged.append(h)
    rest = sorted(google + yahoo, key=lambda h: h.get("published") or "", reverse=True)
    for h in rest:
        key = _norm_title(h["title"])
        if key and key not in seen:
            seen.add(key)
            merged.append(h)
    return merged[:MAX_HEADLINES]


def main():
    names = isin_to_name_map()
    isins = relevant_isins()
    result = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "items": {}}

    print("Hole Ad-hoc-Feed (einmalig)...")
    adhoc_by_isin = fetch_adhoc_all(isins)

    ok, empty = 0, 0
    for isin in isins:
        name = names.get(isin, "")
        ticker = isin_to_ticker.get(isin, "")
        query = name or ticker or isin
        kws = company_keywords(name, ticker)

        adhoc_hl = adhoc_by_isin.get(isin, [])

        g_raw, g_err = fetch_google_news(query)
        google_hl = [h for h in g_raw if headline_relevant(h["title"], kws)]

        y_raw, y_err = fetch_yahoo_news(query)
        yahoo_hl = [h for h in y_raw if headline_relevant(h["title"], kws)]
        # Ticker-Retry wie bisher: manchmal trifft die Ticker-Query die Firma
        # besser als die Namens-Query (Yahoo-spezifische Eigenheit).
        if not yahoo_hl and ticker:
            y_raw2, y_err2 = fetch_yahoo_news(ticker)
            hl2 = [h for h in y_raw2 if headline_relevant(h["title"], kws)]
            if hl2:
                yahoo_hl, y_err = hl2, y_err2

        headlines = merge_headlines(adhoc_hl, google_hl, yahoo_hl)
        dropped = (len(g_raw) - len(google_hl)) + (len(y_raw) - len(yahoo_hl))
        err = g_err or y_err

        result["items"][isin] = {
            "name": name,
            "ticker": ticker,
            "headlines": headlines,
            "error": err if not headlines else None,
        }
        if headlines:
            ok += 1
        else:
            empty += 1
        adhoc_note = f", {len(adhoc_hl)} Ad-hoc" if adhoc_hl else ""
        print(f"  {isin} ({name or ticker}): {len(headlines)} relevant{adhoc_note}"
              + (f", {dropped} Rausch verworfen" if dropped else "")
              + (f" [!{err}]" if err and not headlines else ""))

    save_json(out_path, result)
    print(f"\nDone. {ok} mit News, {empty} ohne. -> {out_path}")


if __name__ == "__main__":
    main()
