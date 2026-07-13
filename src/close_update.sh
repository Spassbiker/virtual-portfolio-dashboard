#!/bin/bash
# Nachbörsen-Update (17:35) als reiner Shell-Job — läuft als Command-Cron direkt
# auf dem Gateway-Host, OHNE LLM-Turn. Dadurch unabhängig von Credits/Session:
# aktualisiert Schlusskurse + Indikatoren, baut das Dashboard, committet/pusht
# und gibt eine kurze Depot-Zusammenfassung aus (wird per Cron nach Telegram
# zugestellt). KEINE Trades — reine Kursaktualisierung.
set -u
cd /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard || exit 1

warn=""
if ! python3 src/healthcheck.py >/tmp/pf_health.log 2>&1; then
  warn="⚠️ Healthcheck-Warnung: $(grep -m1 '✗' /tmp/pf_health.log || echo 'siehe Log'). "
fi

python3 src/update_prices.py >/dev/null 2>&1
python3 src/compute_indicators.py >/dev/null 2>&1
python3 src/risk_report.py >/dev/null 2>&1
python3 src/build_dashboard.py >/dev/null 2>&1

git add data/*.json index.html
if git commit -q -m "Update Schlusskurse" 2>/dev/null; then
  git push -q origin main 2>/dev/null && push="gepusht" || push="Push fehlgeschlagen"
else
  push="nichts zu committen"
fi

python3 - "$warn" "$push" <<'PY'
import json, sys
sys.path.insert(0, "src")
import risk_report
warn, push = sys.argv[1], sys.argv[2]
data = json.load(open("data/depot_status.json"))
d = data["depot"]
e = data.get("etf_depot", {})
gesamt = d.get("gesamtvermoegen", 0) + e.get("gesamtvermoegen", 0)
print("%s📊 Nachbörsen-Update — Gesamtvermögen %.2f € (Aktien %.2f € + ETF %.2f €) | "
      "Portfoliowert Aktien %.2f € / ETF %.2f € | Barbestand Aktien %.2f € / ETF %.2f € (%s)" % (
          warn, gesamt, d["gesamtvermoegen"], e.get("gesamtvermoegen", 0),
          d["portfoliowert"], e.get("portfoliowert", 0),
          d["aktueller_barbestand"], e.get("aktueller_barbestand", 0), push))
for line in risk_report.format_lines(d.get("risiko", {}), d.get("benchmark", {})):
    print(line)
PY
