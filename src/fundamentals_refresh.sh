#!/bin/bash
# Wöchentlicher Fundamentaldaten-Refresh (Sonntag 20:00) — Command-Cron auf dem Gateway-Host.
#
# Warum als Command-Cron mit CLI-Agent-Aufruf?
# Ein agentTurn-Cron bekommt eine restriktive toolsAllow-Policy injiziert;
# das CLI-Backend kann die nicht durchsetzen und bricht ab. Ein normaler
# `openclaw agent` CLI-Aufruf ist dagegen ein vollwertiger Agent-Turn MIT
# allen Tools (Read/Write/web_search). Analog zu sentiment_refresh.sh.
#
# Ablauf: Backup -> LLM recherchiert Kennzahlen pro ISIN -> überschreibt
# data/fundamentalanalyse_ergebnisse.json. Schlägt der Refresh fehl
# (Credits/Timeout), rechnet der 09:00-Manager mit dem letzten Stand weiter.
set -u
cd /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard || exit 1

FUNDA=data/fundamentalanalyse_ergebnisse.json
BACKUP=data/fundamentalanalyse_ergebnisse.backup.json

# Sicherheitskopie des letzten guten Stands.
cp -f "$FUNDA" "$BACKUP"

PROMPT='Aufgabe: Aktualisiere die Fundamentaldaten in /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/data/fundamentalanalyse_ergebnisse.json. Vertragsformat und Regeln stehen in /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/docs/FUNDA_STAGE.md - LIES DIESE DATEI ZUERST.

Vorgehen:
1. Lies das aktuelle JSON. Bestimme die Liste aller ISINs und ihre Sektor-Zuordnung.
2. Für jede ISIN mit echter Recherchemoeglichkeit: web_search nach aktuellen Kennzahlen (KGV/Price-to-Earnings, Umsatzwachstum YoY, Gewinnwachstum YoY, Eigenkapitalquote, Dividendenrendite) und aktuellen Nachrichten (Auftragslage, Guidance, Risiken). Sucht typisch nach "<Firmenname> KGV" bzw. "<Firmenname> financial data 2026" oder Ähnlichem. Yahoo Finance, Boerse Frankfurt, finanzen.net sind gute Quellen.
3. Fuer Cross-Sektor-Duplikate (gleiche ISIN in mehreren Sektoren): identische Kennzahlen verwenden, Text und empfehlung duerfen je nach Sektor-Rolle abweichen.
4. Fuer Platzhalter-Eintraege (aktueller Text enthaelt "Ergaenzt zur Vervollstaendigung" o.ae.) und fuer delistete Papiere: begruendung stehen lassen bzw. Delisting erwaehnen, empfehlung="N/A".
5. Bewertung/Risiko/empfehlung nach den Regeln in FUNDA_STAGE.md ableiten.
6. datum auf heute (YYYY-MM-DD) setzen. aktueller_kurs UNANGETASTET lassen.
7. Schreibe die komplette Datei zurueck nach data/fundamentalanalyse_ergebnisse.json (UTF-8, indent=2, ensure_ascii=false). Alle bestehenden ISINs muessen erhalten bleiben, keine dazu, keine weg.

Antworte am Ende NUR mit: FERTIG N ISINs (N = Anzahl aktualisierter Eintraege).'

timeout 900 openclaw agent \
  --session-key "portfolio-fundamentals" \
  --thinking off \
  -m "$PROMPT" \
  >/tmp/pf_funda_agent.log 2>&1

# Basissanity: gültige JSON-Datei mit gleicher Sektor-Struktur? Sonst Backup zurück.
python3 - <<'PY'
import json, sys, shutil, os
funda = "data/fundamentalanalyse_ergebnisse.json"
backup = "data/fundamentalanalyse_ergebnisse.backup.json"
try:
    new = json.load(open(funda, encoding="utf-8"))
    old = json.load(open(backup, encoding="utf-8"))
    new_sectors = set((new.get("sektoren") or {}).keys())
    old_sectors = set((old.get("sektoren") or {}).keys())
    if new_sectors != old_sectors:
        raise ValueError(f"Sektoren divergieren: neu={new_sectors} vs. alt={old_sectors}")
    new_isins = {i.get("isin") for sec in new.get("sektoren", {}).values() for i in sec if i.get("isin")}
    old_isins = {i.get("isin") for sec in old.get("sektoren", {}).values() for i in sec if i.get("isin")}
    missing = old_isins - new_isins
    if missing:
        raise ValueError(f"{len(missing)} ISINs verloren: {sorted(missing)[:5]}...")
except Exception as e:
    shutil.copyfile(backup, funda)
    print("⚠️ Fundamental-Refresh verworfen: %s. Backup wiederhergestellt." % e)
    sys.exit(0)

import datetime
today = datetime.date.today().strftime("%Y-%m-%d")
frisch = sum(1 for sec in new["sektoren"].values() for i in sec if i.get("datum") == today)
gesamt = sum(len(sec) for sec in new["sektoren"].values())
if frisch < gesamt * 0.5:
    print("⚠️ Fundamental-Refresh: nur %d/%d Eintraege auf heute datiert. Bitte pruefen." % (frisch, gesamt))
else:
    print("NO_REPLY")  # Erfolg still, kein Chat-Spam am Sonntagabend
PY
