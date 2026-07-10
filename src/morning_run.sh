#!/bin/bash
# Täglicher Portfolio-Manager (09:00) als reiner Shell-Job — läuft als Command-Cron
# direkt auf dem Gateway-Host, OHNE LLM-Turn. Dadurch unabhängig von Credits und
# von Heartbeat-Kollisionen der Hauptsession: der Stop-Loss und die regelbasierten
# Trades laufen GARANTIERT jeden Handelstag.
#
# Ablauf: Healthcheck -> Kurse -> Indikatoren -> News -> Empfehlung -> Trades
#         ausführen -> Dashboard bauen -> commit/push -> Telegram-Zusammenfassung.
#
# Das KI-Sentiment (data/sentiment_scores.json) wird verwendet, falls vorhanden;
# ein optionaler Best-Effort-Vorlauf in der Hauptsession kann es vorher auffrischen.
# Bei Healthcheck-Fehler werden KEINE Trades ausgeführt (nur Warnung + Report).
set -u
cd /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard || exit 1

TODAY="$(date +%Y-%m-%d)"
warn=""
traded=1

if ! python3 src/healthcheck.py >/tmp/pf_health_am.log 2>&1; then
  warn="⚠️ Healthcheck FEHLGESCHLAGEN — KEINE Trades ausgeführt: $(grep -m1 '✗' /tmp/pf_health_am.log || echo 'siehe Log'). "
  traded=0
fi

python3 src/update_prices.py            >/dev/null 2>&1
python3 src/compute_indicators.py       >/dev/null 2>&1
python3 src/refresh_chart_narrative.py  >/dev/null 2>&1
python3 src/sanitize_fundamentals.py    >/dev/null 2>&1
python3 src/fetch_news.py               >/dev/null 2>&1

if [ "$traded" = "1" ]; then
  # Regelbasierte Empfehlung (nutzt vorhandenes sentiment_scores.json), dann ausführen.
  python3 src/update_depot.py --recommend >/dev/null 2>&1
  python3 src/update_depot.py              >/dev/null 2>&1
fi

python3 src/build_dashboard.py >/dev/null 2>&1
python3 src/risk_report.py >/dev/null 2>&1

git add data/*.json index.html
if git commit -q -m "Daily 09:00: Portfolio-Manager (Stop-Loss + regelbasierte Trades)" 2>/dev/null; then
  git push -q origin main 2>/dev/null && push="gepusht" || push="Push fehlgeschlagen"
else
  push="nichts zu committen"
fi

python3 - "$warn" "$push" "$TODAY" <<'PY'
import json, sys
sys.path.insert(0, "src")
import risk_report
warn, push, today = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open("data/depot_status.json"))["depot"]
hist = d.get("transaktionshistorie", [])
heute = [t for t in hist if t.get("datum") == today]
if heute:
    zeilen = []
    for t in heute:
        gv = t.get("gewinn_verlust")
        gv_s = ""
        if t.get("typ") == "Verkauf" and gv is not None:
            gv_s = " (%+.2f€)" % gv
        zeilen.append("%s %sx %s zu %.2f€%s" % (t["typ"], t["stueck"], t["wertpapier"], t["kurs"], gv_s))
    trades = "Trades: " + " · ".join(zeilen)
else:
    trades = "Keine Trades (keine Signale/Stop-Loss ausgelöst)"
print("%s📊 Tages-Lauf 09:00 — %s | Gesamtvermögen %.2f € | Portfoliowert %.2f € | "
      "Barbestand %.2f € (%s)" % (warn, trades, d["gesamtvermoegen"], d["portfoliowert"],
                                   d["aktueller_barbestand"], push))
for line in risk_report.format_lines(d.get("risiko", {}), d.get("benchmark", {})):
    print(line)
PY
