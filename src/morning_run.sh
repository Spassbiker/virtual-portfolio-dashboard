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

# Persistente Logs: /tmp überlebt keinen Reboot — Ausfälle waren dann nicht mehr
# nachvollziehbar. Ein Tagesordner pro Lauf, Rotation nach 30 Tagen.
LOGDIR="logs/$TODAY"
mkdir -p "$LOGDIR"
find logs -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null

if ! python3 src/healthcheck.py >"$LOGDIR/health_am.log" 2>&1; then
  warn="⚠️ Healthcheck FEHLGESCHLAGEN — KEINE Trades ausgeführt: $(grep -m1 '✗' "$LOGDIR/health_am.log" || echo 'siehe Log'). "
  traded=0
fi

# Regressionstest-Gate: sind die Engine-Tests rot, ist die Handelslogik nicht
# vertrauenswürdig — Kurse/Dashboard laufen weiter, aber es werden KEINE Trades
# ausgeführt (gleiche Sicherung wie beim Healthcheck).
if ! python3 -m unittest discover -s tests -q >"$LOGDIR/tests_am.log" 2>&1; then
  fail_line="$(grep -m1 -E '^(FAIL|ERROR):' "$LOGDIR/tests_am.log" || echo "siehe $LOGDIR/tests_am.log")"
  warn="${warn}🔴 REGRESSIONSTESTS ROT — KEINE Trades ausgeführt: ${fail_line}. "
  traded=0
fi

# run_step führt ein Python-Skript aus, protokolliert stderr (statt es nach
# /dev/null zu verschlucken) und hängt bei Absturz eine laute Warnung an $warn.
# So bleibt kein stiller Crash mehr unbemerkt (Lehre aus dem 9-Tage-Ausfall:
# update_depot.py crashte an trend=null und niemand hat es gemerkt).
run_step() {
  local script="$1"; shift
  local log="$LOGDIR/$(basename "$script" .py)_am.log"
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
run_step src/etf_ranking.py
run_step src/refresh_chart_narrative.py
run_step src/sanitize_fundamentals.py
run_step src/prune_analysis.py
run_step src/fetch_news.py

# Sentiment-Kalibrierung: Score+Kurs von heute loggen, alte Einträge mit
# Forward-Return nachtragen. Reine Beobachtung, beeinflusst keine Trades.
run_step src/sentiment_calibration.py log
run_step src/sentiment_calibration.py backfill
# Dito für den ETF-Composite (misst, ob Ranking/70er-Schwelle Alpha liefern).
run_step src/etf_composite_log.py log
run_step src/etf_composite_log.py backfill

if [ "$traded" = "1" ]; then
  # Regelbasierte Empfehlung (nutzt vorhandenes sentiment_scores.json), dann ausführen.
  # Ein Crash schreibt depot_status.json NICHT (save nur am Skriptende), der Stand
  # bleibt also konsistent; run_step sorgt dafür, dass der Fehler nicht mehr still
  # bleibt, sondern per $warn oben in die Telegram-Zusammenfassung wandert.
  run_step src/update_depot.py --recommend
  run_step src/update_depot.py
  # ETF-Sleeve (eigenes 5.000€-Budget, ranking-basiert): gleiche Healthcheck-Gate.
  run_step src/update_etf_depot.py --recommend
  run_step src/update_etf_depot.py
fi

run_step src/risk_report.py
# Equity-Kurve (V1): Tageszeile Gesamtvermögen + Benchmarks für das Dashboard.
run_step src/log_vermoegen.py
run_step src/build_dashboard.py

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
data = json.load(open("data/depot_status.json"))
d = data["depot"]
e = data.get("etf_depot", {})

def trade_zeilen(hist, today):
    heute = [t for t in hist if t.get("datum") == today]
    zeilen = []
    for t in heute:
        gv = t.get("gewinn_verlust")
        gv_s = ""
        if t.get("typ") == "Verkauf" and gv is not None:
            gv_s = " (%+.2f€)" % gv
        zeilen.append("%s %sx %s zu %.2f€%s" % (t["typ"], t["stueck"], t["wertpapier"], t["kurs"], gv_s))
    return zeilen

aktien_zeilen = trade_zeilen(d.get("transaktionshistorie", []), today)
etf_zeilen = trade_zeilen(e.get("transaktionshistorie", []), today)

if aktien_zeilen or etf_zeilen:
    bloecke = []
    if aktien_zeilen:
        bloecke.append("Aktien: " + " · ".join(aktien_zeilen))
    if etf_zeilen:
        bloecke.append("ETF: " + " · ".join(etf_zeilen))
    trades = " | ".join(bloecke)
else:
    trades = "Keine Trades (keine Signale/Stop-Loss ausgelöst)"

gesamt = d.get("gesamtvermoegen", 0) + e.get("gesamtvermoegen", 0)
print("%s📊 Tages-Lauf 09:00 — %s | Gesamtvermögen %.2f € (Aktien %.2f € + ETF %.2f €) | "
      "Barbestand Aktien %.2f € / ETF %.2f € (%s)" % (
          warn, trades, gesamt, d["gesamtvermoegen"], e.get("gesamtvermoegen", 0),
          d["aktueller_barbestand"], e.get("aktueller_barbestand", 0), push))
for line in risk_report.format_lines(d.get("risiko", {}), d.get("benchmark", {}), d.get("korrelation", {})):
    print(line)
PY
