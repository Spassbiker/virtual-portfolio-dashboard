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

# run_step führt ein Python-Skript aus, protokolliert stderr (statt es nach
# /dev/null zu verschlucken) und hängt bei Absturz eine laute Warnung an $warn.
# So bleibt kein stiller Crash mehr unbemerkt (Lehre aus dem 9-Tage-Ausfall:
# update_depot.py crashte an trend=null und niemand hat es gemerkt). Spiegelt
# den Wrapper aus morning_run.sh.
run_step() {
  local script="$1"; shift
  local log="/tmp/pf_$(basename "$script" .py)_pm.log"
  if ! python3 "$script" "$@" >/dev/null 2>"$log"; then
    local msg
    # Letzte Traceback-Zeile (z.B. "ValueError: ...") ist am aussagekräftigsten;
    # Fallback auf letzte nicht-leere Log-Zeile, sonst Log-Pfad.
    msg="$(grep -E '^[A-Za-z_.]+(Error|Exception|Warning):' "$log" | tail -1)"
    [ -z "$msg" ] && msg="$(grep -v '^[[:space:]]*$' "$log" | tail -1)"
    [ -z "$msg" ] && msg="siehe $log"
    warn="${warn}🔴 FEHLER in $(basename "$script") $*: $(echo "$msg" | tail -c 200). "
    return 1
  fi
  return 0
}

run_step src/update_prices.py
run_step src/compute_indicators.py
run_step src/risk_report.py
run_step src/build_dashboard.py

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
