#!/bin/bash
# Täglicher Opportunity-Scan (werktags 08:30) — Command-Cron auf dem Gateway-Host.
#
# Idee: Ein LLM-Agent screent aktuellen Marktnews-Flow/Momentum und schlägt
# max. 3 neue EU-handelbare Kandidaten pro Lauf vor. Sie werden als
# "Watch-Kandidat" in fundamentalanalyse_ergebnisse.json UND als Skelett-
# Eintrag in chartanalyse_ergebnisse.json ergänzt. update_depot.py behandelt
# sie als Watch (kein Kauf), bis compute_indicators genug Historie geliefert
# hat (SMA200 verfügbar).
#
# Warum als Command-Cron mit CLI-Agent-Aufruf? Gleich wie
# fundamentals_refresh.sh / sentiment_refresh.sh: agentTurn-Cron kann keine
# tool-Policy erzwingen, CLI-Aufruf bekommt alle Tools inkl. web_search.
#
# Bei Fehler: Backup wiederherstellen. Kein Trade wird davon abhängig gemacht —
# der 09:00-Manager läuft egal ob dieses Skript Erfolg hatte.
set -u
cd /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard || exit 1

FUNDA=data/fundamentalanalyse_ergebnisse.json
CHART=data/chartanalyse_ergebnisse.json
BACKUP_F=data/fundamentalanalyse_ergebnisse.opportunity_backup.json
BACKUP_C=data/chartanalyse_ergebnisse.opportunity_backup.json

cp -f "$FUNDA" "$BACKUP_F"
cp -f "$CHART" "$BACKUP_C"

PROMPT='Aufgabe: Opportunity-Scan. Finde MAXIMAL 3 neue, aktuell interessante Wertpapiere fuer das virtuelle Depot und ergaenze sie als Watch-Kandidaten.

WORKING DIR: /home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard

Kontext-Dateien (LIES ZUERST):
- data/fundamentalanalyse_ergebnisse.json (bestehendes Universum)
- data/chartanalyse_ergebnisse.json (bestehendes Chart-Universum)
- data/depot_status.json (aktuelle Positionen)
- docs/FUNDA_STAGE.md (Datenvertrag Funda)

Vorgehen:
1. Bestimme alle ISINs, die bereits im Universum sind. Diese NICHT nochmal vorschlagen.
2. Recherchiere aktuelle Marktlage: Momentum-Leader, Sektor-Rotation, IPOs, Newsflow (Yahoo Finance, Boerse Frankfurt, finanzen.net, seekingalpha, marketwatch). Fokus: EUR-Notierung an XETRA/Euronext/Frankfurt ODER US-Wert mit sauberem EUR-Listing.
3. Waehle MAX 3 Kandidaten mit klarer Story (Warum JETZT? Katalysator? Momentum? Bewertungswende?).
4. Fuer jeden Kandidaten:
   a. In data/fundamentalanalyse_ergebnisse.json unter passendem Sektor einfuegen:
      - wertpapier, isin (verifiziert), Kennzahlen soweit recherchierbar (kgv, umsatzwachstum_yoy, gewinnwachstum_yoy, eigenkapitalquote, dividendenrendite)
      - "bewertung": "Attraktiv" oder "Neutral"
      - "risiko": realistisch abgeleitet
      - "empfehlung": "Halten" (nicht "Kaufen" - das Scoring soll das selbst herausfinden)
      - "begruendung": MUSS mit "Watch-Kandidat aus Opportunity-Scan: " beginnen, dann 1-2 Saetze zur Story
      - "datum": heute YYYY-MM-DD
      - "aktueller_kurs": null
   b. In data/chartanalyse_ergebnisse.json unter demselben Sektor Skelett-Eintrag anlegen:
      - wertpapier, isin, sektor
      - "empfehlung": "Halten"
      - "trend": null
      - "signal": "Watch"
      - alle Zahlenfelder (rsi_14, macd, sma_50, sma_200, unterstuetzung, widerstand, aktueller_kurs): null
      - "begruendung": "Watch-Kandidat aus Opportunity-Scan - Historie wird bei den naechsten compute_indicators-Laeufen aufgebaut."
      - "datum": heute
   c. Sektor darf existieren oder neu angelegt werden. Nur passende Sektor-Namen verwenden (siehe bestehende Sektoren).
5. Wenn KEINE ueberzeugenden Kandidaten gefunden werden, fasse nichts an. Lieber nichts als Muell.

HARTE FILTER:
- ISIN muss verifizierbar existieren (US..., DE..., FR..., NL..., GB... etc.)
- Kein reines US-Papier ohne EUR-Handelbarkeit
- Keine bestehenden ISINs erneut vorschlagen
- Keine Platzhaltertexte, keine erfundenen Kennzahlen

Schreibe beide Dateien komplett zurueck (UTF-8, indent=2, ensure_ascii=false). Bestehende Eintraege UNANGETASTET lassen.

Antworte am Ende NUR mit: FERTIG N Kandidaten (N = wie viele du hinzugefuegt hast, 0..3).'

timeout 600 openclaw agent \
  --session-key "portfolio-opportunity" \
  --thinking off \
  -m "$PROMPT" \
  >/tmp/pf_opportunity_agent.log 2>&1

# Sanity: JSON gueltig? Sektor-Struktur nicht zerstoert? Keine bestehenden ISINs verloren?
python3 - <<'PY'
import json, shutil, sys, datetime
FUNDA = "data/fundamentalanalyse_ergebnisse.json"
CHART = "data/chartanalyse_ergebnisse.json"
BF = "data/fundamentalanalyse_ergebnisse.opportunity_backup.json"
BC = "data/chartanalyse_ergebnisse.opportunity_backup.json"

def isins(data):
    return {i.get("isin") for sec in data.get("sektoren", {}).values() for i in sec if i.get("isin")}

try:
    fnew = json.load(open(FUNDA, encoding="utf-8"))
    fold = json.load(open(BF, encoding="utf-8"))
    cnew = json.load(open(CHART, encoding="utf-8"))
    cold = json.load(open(BC, encoding="utf-8"))
    # Sektoren-Set darf sich erweitern, aber KEINE alten Sektoren verschwinden.
    missing_f = set((fold.get("sektoren") or {}).keys()) - set((fnew.get("sektoren") or {}).keys())
    missing_c = set((cold.get("sektoren") or {}).keys()) - set((cnew.get("sektoren") or {}).keys())
    if missing_f or missing_c:
        raise ValueError(f"Sektor verschwunden: funda={missing_f} chart={missing_c}")
    lost_f = isins(fold) - isins(fnew)
    lost_c = isins(cold) - isins(cnew)
    if lost_f or lost_c:
        raise ValueError(f"ISIN verloren: funda={len(lost_f)} chart={len(lost_c)}")
    added_f = isins(fnew) - isins(fold)
    if len(added_f) > 3:
        raise ValueError(f"Zu viele neue ISINs im Funda: {len(added_f)} (max 3)")
except Exception as e:
    shutil.copyfile(BF, FUNDA)
    shutil.copyfile(BC, CHART)
    print(f"⚠️ Opportunity-Scan verworfen: {e}. Backup wiederhergestellt.")
    sys.exit(0)

if not added_f:
    print("NO_REPLY")
else:
    names = []
    for sec in fnew.get("sektoren", {}).values():
        for it in sec:
            if it.get("isin") in added_f:
                names.append(f"{it.get('wertpapier','?')} [{it.get('isin')}]")
    print(f"🔎 Opportunity-Scan: {len(added_f)} neue Watch-Kandidat(en): {', '.join(names)}")
PY
