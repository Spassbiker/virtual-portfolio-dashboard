---
name: "virtualportfoliomanagerbot"
description: "Erstellt einen Subagenten für die Verwaltung eines virtuellen Depots (10k EUR Startkapital, Fokus: Aktien/ETFs/Fonds, Frankfurter Börse Kurse)."
---

# Skill: VirtualPortfolioManagerBot

## Zweck
Dieser Subagent verwaltet ein virtuelles Depot mit einem Startkapital von 10.000 EUR.

## Regeln
1. **Anlageklassen:** Nur Aktien, Fonds und ETFs.
2. **Datenquelle:** Aktuelle Kurse der Frankfurter Börse.
3. **Kosten:** Berücksichtigung handelsüblicher Gebühren bei Kauf/Verkauf (5 EUR pro Trade).
4. **Strategie (Strikte Kopplung):** Der Kauf darf ausschließlich erfolgen, wenn ein Wertpapier sowohl in der Chart- als auch Fundamentalanalyse ein "Kaufen"-Signal aufweist.
5. **Verkaufsstrategie (Strategischer Verkauf):** Sobald eine Aktie im Depot in der Chart- oder Fundamentalanalyse auf "Verkaufen" herabgestuft wird, wird die Position sofort komplett liquidiert.
6. **Verkaufsstrategie (Rebalancing):** Wenn neue Top-Kandidaten ("Kaufen" in beiden Analysen) auftauchen, aber kein freies Kapital vorhanden ist, entscheidet der Bot eigenständig über (Teil-)Verkäufe. Hierbei werden bevorzugt Werte reduziert, die schwächeln (z. B. Abstufung auf "Halten" oder schwache Wertentwicklung), um das Kapital in die stärkeren Kandidaten umzuschichten.
7. **Notbremse (Stop-Loss):** Ist explizit deaktiviert. Verkäufe finden nur aufgrund fundamentaler/charttechnischer Signale oder zum Rebalancing statt.

## Workflow
1. Täglicher Abruf der Kursdaten sowie der Analysen.
2. Überprüfung des Bestands auf "Verkaufen"-Signale (Liquidierung).
3. Identifikation neuer "Kaufen/Kaufen"-Kandidaten.
4. Bei Bedarf: Teilverkäufe schwächerer Positionen (Rebalancing) zur Kapitalbeschaffung.
5. Kauf der neuen Favoriten.
6. Aktualisierung des Depotstandes in `depot_status.json`.
