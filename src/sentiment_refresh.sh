#!/bin/bash
# KI-Sentiment-Vorlauf (08:50, Mo–Fr) — läuft als Command-Cron auf dem Gateway-Host.
#
# Warum als Command-Cron mit CLI-Agent-Aufruf statt agentTurn-Cron?
# Ein agentTurn-Cron bekommt zwangsweise eine restriktive toolsAllow-Policy
# injiziert; das CLI-Backend (claude-cli) kann die nicht durchsetzen und bricht
# sofort ab ("cannot enforce runtime toolsAllow"). Ein normaler `openclaw agent`
# CLI-Aufruf ist dagegen ein vollwertiger Agent-Turn MIT allen Tools (Read/Write).
# Damit ist der LLM-Schritt (News -> Sentiment) zuverlässig cron-getriggert.
#
# Ablauf: News frisch holen -> LLM bewertet -> data/sentiment_scores.json.
# Der 09:00-Manager (morning_run.sh) liest diese Datei danach. Schlägt dieser
# Vorlauf fehl (z.B. keine Credits), rechnet der 09:00-Lauf mit dem letzten
# vorhandenen Sentiment weiter — nichts bricht, Stop-Loss/Trades laufen normal.
set -u
cd /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard || exit 1

# Frische Schlagzeilen holen (idempotent; der 09:00-Lauf holt sie ohnehin nochmal).
python3 src/fetch_news.py >/tmp/pf_sentiment_news.log 2>&1

PROMPT='Lies /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data/news_raw.json. Bewerte fuer JEDE darin enthaltene ISIN die Schlagzeilen der letzten Tage als Nachrichtenstimmung fuer genau dieses Unternehmen. Format-Referenz: /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/docs/SENTIMENT_STAGE.md. Vergib sentiment_score als Ganzzahl -3..+3, veto true nur bei akutem Kaufvermeidungsgrund, sonst false, plus eine knappe begruendung (1 Satz). Ignoriere Schlagzeilen die offensichtlich eine andere Firma betreffen (score 0). Schreibe das Ergebnis EXAKT im Vertragsformat nach /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data/sentiment_scores.json - ueberschreibe die Datei komplett, generated_at im Format YYYY-MM-DD HH:MM. Antworte am Ende nur mit: FERTIG N ISINs.'

timeout 300 openclaw agent \
  --session-key "portfolio-sentiment" \
  --thinking off \
  -m "$PROMPT" \
  >/tmp/pf_sentiment_agent.log 2>&1

# Kurze Bestätigung auf stdout (wird von cron als Ergebnis geliefert).
python3 - <<'PY'
import json, datetime, sys
try:
    d = json.load(open("data/sentiment_scores.json"))
    ga = d.get("generated_at", "?")
    n = len(d.get("scores", {}))
    today = datetime.date.today().strftime("%Y-%m-%d")
    if ga.startswith(today):
        print("NO_REPLY")  # Erfolg, still — kein Chat-Spam vor dem 09:00-Report
    else:
        print("⚠️ Sentiment-Vorlauf: Datei nicht auf heute aktualisiert (generated_at %s). 09:00-Lauf nutzt vorhandenes Sentiment." % ga)
except Exception as e:
    print("⚠️ Sentiment-Vorlauf fehlgeschlagen: %s. 09:00-Lauf nutzt vorhandenes Sentiment." % e)
PY
