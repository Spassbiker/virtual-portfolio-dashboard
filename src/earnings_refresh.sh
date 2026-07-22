#!/bin/bash
# Wöchentlicher Earnings-/Guidance-Refresh (#1) — Command-Cron auf dem Gateway-Host.
#
# Warum als Command-Cron mit CLI-Agent-Aufruf?
# Ein agentTurn-Cron bekommt eine restriktive toolsAllow-Policy injiziert; das
# CLI-Backend kann die nicht durchsetzen und bricht ab. Ein normaler
# `openclaw agent` CLI-Aufruf ist dagegen ein vollwertiger Agent-Turn MIT allen
# Tools (Read/Write/web_search). Analog zu sentiment_refresh.sh / fundamentals_refresh.sh.
#
# Ablauf: Backup -> LLM recherchiert je ISIN den letzten Bericht + Ausblick ->
# data/earnings_scores.json. Schlägt der Refresh fehl (Credits/Timeout), rechnet
# der 09:00-Manager ohne Earnings-Summanden weiter — nichts bricht.
set -u
cd /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard || exit 1

EARN=data/earnings_scores.json
BACKUP=data/earnings_scores.backup.json

# Sicherheitskopie des letzten guten Stands (falls vorhanden).
[ -f "$EARN" ] && cp -f "$EARN" "$BACKUP"

PROMPT='Aufgabe: Erzeuge/aktualisiere /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data/earnings_scores.json. Vertragsformat, Score-Leitfaden und Regeln stehen in /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/docs/EARNINGS_STAGE.md - LIES DIESE DATEI ZUERST.

WICHTIG: Dieser Lauf ist ein EINMALIGER CLI-Turn ohne Folge-Turn. Spawne KEINE Subagents (Agent/sessions_spawn) und rufe NIEMALS sessions_yield auf - wenn du yieldest, endet der Prozess sofort und die Datei wird nie geschrieben. Recherchiere jede ISIN direkt und sequenziell selbst mit web_search/WebSearch/WebFetch im selben Turn.

Vorgehen:
1. Lies /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data/fundamentalanalyse_ergebnisse.json und sammle ALLE ISINs (das Universum) mit Firmennamen.
2. Fuer jede ISIN: web_search nach dem JUENGSTEN Quartals-/Jahresbericht und der aktuellen GUIDANCE (Ausblick). Yahoo Finance, boerse-frankfurt.de, finanzen.net, die IR-Seite des Unternehmens sind gute Quellen.
3. Bewerte FORWARD-LOOKING (nicht die Tagesstimmung): earnings_score -3..+3 nach dem Leitfaden in EARNINGS_STAGE.md, guidance_richtung (angehoben|bestaetigt|gesenkt|keine), horizon (Freitext, worauf sich die Guidance bezieht), report_datum (YYYY-MM-DD), confidence 0.0-1.0.
4. Kein belastbarer Bericht gefunden: earnings_score 0, confidence niedrig, guidance_richtung "keine", begruendung "kein aktueller Bericht gefunden". Erfinde keine Zahlen.

Schreibe die komplette Datei nach data/earnings_scores.json (UTF-8, indent=2, ensure_ascii=false), generated_at im Format YYYY-MM-DD HH:MM.

Antworte am Ende NUR mit: FERTIG N ISINs (N = Anzahl bewerteter ISINs).'

timeout 900 openclaw agent \
  --session-key "portfolio-earnings" \
  --thinking off \
  -m "$PROMPT" \
  >/tmp/pf_earnings_agent.log 2>&1

# Basissanity: gültige JSON-Datei mit scores-Objekt? Sonst Backup zurück (falls vorhanden).
python3 - <<'PY'
import json, sys, shutil, os, datetime
earn = "data/earnings_scores.json"
backup = "data/earnings_scores.backup.json"
try:
    new = json.load(open(earn, encoding="utf-8"))
    scores = new.get("scores")
    if not isinstance(scores, dict) or not scores:
        raise ValueError("scores fehlt oder leer")
except Exception as e:
    if os.path.exists(backup):
        shutil.copyfile(backup, earn)
        print("⚠️ Earnings-Refresh verworfen: %s. Backup wiederhergestellt." % e)
    else:
        print("⚠️ Earnings-Refresh fehlgeschlagen: %s. Keine Datei geschrieben (Engine rechnet ohne Earnings weiter)." % e)
    sys.exit(0)

ga = new.get("generated_at", "?")
today = datetime.date.today().strftime("%Y-%m-%d")
if str(ga).startswith(today):
    print("NO_REPLY")  # Erfolg still, kein Chat-Spam am Sonntagabend
else:
    print("⚠️ Earnings-Refresh: Datei nicht auf heute datiert (generated_at %s). 09:00-Lauf nutzt vorhandenen Stand." % ga)
PY
