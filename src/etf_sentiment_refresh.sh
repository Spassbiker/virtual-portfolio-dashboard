#!/bin/bash
# KI-ETF-Sentiment-Vorlauf (08:52, Mo-Fr) — läuft als Command-Cron auf dem Gateway-Host.
#
# Analog zu sentiment_refresh.sh (Aktien), aber themen-/sektorbasiert für den
# ETF-Sleeve (siehe docs/ETF_SENTIMENT_STAGE.md). Rein informativ: der
# ETF-Sleeve ist Buy-and-Hold, kein automatisierter Kauf/Verkauf auf Basis
# dieses Scores. build_dashboard.py liest die Datei danach nur zur Anzeige.
set -u
cd /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard || exit 1

python3 src/fetch_etf_news.py >/tmp/pf_etf_sentiment_news.log 2>&1

PROMPT='Lies /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data/etf_news_raw.json. Bewerte fuer JEDE darin enthaltene ISIN die Schlagzeilen der letzten Tage als Themen-/Sektorstimmung (Feld thema, nicht Einzelfirma). Format-Referenz: /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/docs/ETF_SENTIMENT_STAGE.md. Vergib sentiment_score als Ganzzahl -3..+3 plus eine knappe begruendung (1 Satz) und uebernimm das Feld typ (A oder B) aus der Quelldatei. Ignoriere Schlagzeilen ohne Bezug zum Thema (score 0). Schreibe das Ergebnis EXAKT im Vertragsformat nach /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data/etf_sentiment_scores.json - ueberschreibe die Datei komplett, generated_at im Format YYYY-MM-DD HH:MM. Antworte am Ende nur mit: FERTIG N ETF-ISINs.'

timeout 300 openclaw agent \
  --session-key "portfolio-etf-sentiment" \
  --thinking off \
  -m "$PROMPT" \
  >/tmp/pf_etf_sentiment_agent.log 2>&1

python3 - <<'PY'
import json, datetime
try:
    d = json.load(open("data/etf_sentiment_scores.json"))
    ga = d.get("generated_at", "?")
    n = len(d.get("scores", {}))
    today = datetime.date.today().strftime("%Y-%m-%d")
    if ga.startswith(today):
        print("NO_REPLY")
    else:
        print("⚠️ ETF-Sentiment-Vorlauf: Datei nicht auf heute aktualisiert (generated_at %s)." % ga)
except Exception as e:
    print("⚠️ ETF-Sentiment-Vorlauf fehlgeschlagen: %s." % e)
PY
