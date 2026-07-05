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
import urllib.request
import urllib.parse
from datetime import datetime

base_dir = "/home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data"
depot_path = os.path.join(base_dir, "depot_status.json")
chart_path = os.path.join(base_dir, "chartanalyse_ergebnisse.json")
funda_path = os.path.join(base_dir, "fundamentalanalyse_ergebnisse.json")
out_path = os.path.join(base_dir, "news_raw.json")

# Reuse the ISIN->EUR/US ticker map used elsewhere (kept in sync manually).
isin_to_ticker = {
    'IT0003856405': 'LDO.MI', 'DE000ENER6Y0': 'ENR.DE', 'GB00B63H8491': 'RRU.DE',
    'FR0000121329': 'HO.PA', 'NL0010273215': 'ASML.AS', 'DE000A0D9PT0': 'MTX.DE',
    'DE0007030009': 'RHM.DE', 'DE0007164600': 'SAP.DE', 'FR0000073272': 'SAF.PA',
    'DE000ENAG999': 'EOAN.DE', 'DE0007037129': 'RWE.DE', 'DE0006231004': 'IFX.DE',
    'NL0000235190': 'AIR.PA', 'US72703X1063': '85H1.DE', 'DE0006095003': 'ECV.DE',
    'FR0010221234': 'ETL.PA', 'DE000HAG0005': 'HAG.DE', 'DE000A0DJ6J9': 'S92.DE',
    'DE000A0D6554': 'NDX1.DE', 'DE0005936124': 'OHB.DE', 'DE000A2YN900': 'TMV.DE',
    'DE000A2E4K43': 'DHER.DE', 'DE0005557508': 'DTE.DE', 'DE000A0WMPJ6': 'AIXA.DE',
    'DK0061539921': 'VWS.CO', 'DK0060094928': 'ORSTED.CO', 'GB0002634946': 'BA.L',
    'US65339F1012': 'NEE', 'US6668071029': 'NOC', 'US3695501086': 'GD',
    'US5398301094': 'LMT', 'FR0014004L86': 'AM.PA', 'US0970231058': 'BA',
    'US0003611052': 'AIR', 'US4282911084': 'HXL', 'LU0088087324': 'SESG.PA',
    'US57778K1051': 'MAXR', 'US7731221062': 'RKLB', 'US46269C1027': 'IRDM',
    'IL0010825102': 'GILT', 'US79466L3024': 'CRM', 'US68389X1054': 'ORCL',
    'US67066G1040': 'NVDA', 'US5949181045': 'MSFT', 'US02079K3059': 'GOOG'
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def isin_to_name_map():
    names = {}
    for path in (chart_path, funda_path):
        try:
            data = load_json(path)
        except Exception:
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
    try:
        depot = load_json(depot_path).get("depot", {})
        for p in depot.get("positionen", []):
            if p.get("isin"):
                isins.add(p["isin"])
    except Exception:
        pass
    try:
        chart = load_json(chart_path)
        funda = load_json(funda_path)
        chart_buys = {i["isin"] for _, its in chart.get("sektoren", {}).items()
                      for i in its if i.get("empfehlung", "").lower() == "kaufen" and i.get("isin")}
        funda_buys = {i["isin"] for _, its in funda.get("sektoren", {}).items()
                      for i in its if (i.get("empfehlung") or "").lower() == "kaufen" and i.get("isin")}
        isins |= (chart_buys & funda_buys)
    except Exception:
        pass
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
            "published": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else None,
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
        headlines, err = fetch_headlines(query)
        if not headlines and ticker:
            headlines, err = fetch_headlines(ticker)
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
        print(f"  {isin} ({name or ticker}): {len(headlines)} Schlagzeilen"
              + (f" [!{err}]" if err else ""))

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nDone. {ok} mit News, {empty} ohne. -> {out_path}")


if __name__ == "__main__":
    main()
