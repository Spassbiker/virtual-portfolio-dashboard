import json

# Lese JSON-Dateien
with open('data/chartanalyse_ergebnisse.json', 'r', encoding='utf-8') as f:
    chart_data = f.read()
with open('data/fundamentalanalyse_ergebnisse.json', 'r', encoding='utf-8') as f:
    funda_data = f.read()
with open('data/depot_status.json', 'r', encoding='utf-8') as f:
    depot_data = f.read()

html_template = """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Virtual Portfolio Dashboard</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; text-align: center; margin-bottom: 30px; }
        h2, h3 { color: #34495e; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 30px; font-size: 0.95em; }
        th, td { padding: 12px 15px; border-bottom: 1px solid #ddd; text-align: left; }
        th { background-color: #34495e; color: white; }
        tr:hover { background-color: #f9f9f9; }
        .badge { padding: 6px 12px; border-radius: 4px; font-weight: bold; font-size: 0.85em; display: inline-block; text-align: center; width: 80px; }
        .buy { background-color: #d4edda; color: #155724; }
        .hold { background-color: #fff3cd; color: #856404; }
        .sell { background-color: #f8d7da; color: #721c24; }
        .tab-buttons { border-bottom: 2px solid #34495e; margin-bottom: 20px; }
        .tab-button { background-color: #ecf0f1; border: none; padding: 12px 25px; cursor: pointer; font-size: 16px; border-radius: 5px 5px 0 0; margin-right: 5px; font-weight: bold; color: #7f8c8d; transition: all 0.3s; }
        .tab-button:hover { background-color: #bdc3c7; }
        .tab-button.active { background-color: #34495e; color: white; }
        .tab-content { display: none; animation: fadeIn 0.5s; }
        .tab-content.active { display: block; }
        .sector-title { background-color: #ecf0f1; padding: 10px 15px; border-left: 5px solid #34495e; margin-top: 40px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: #f8f9fa; padding: 20px; border-radius: 8px; border: 1px solid #dee2e6; text-align: center; }
        .stat-card h4 { margin: 0 0 10px 0; color: #6c757d; font-size: 0.9em; text-transform: uppercase; }
        .stat-card p { margin: 0; font-size: 1.5em; font-weight: bold; color: #2c3e50; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 Virtual Portfolio Dashboard</h1>
        
        <div class="tab-buttons">
            <button class="tab-button active" onclick="openTab(event, 'chart')">Chartanalyse</button>
            <button class="tab-button" onclick="openTab(event, 'funda')">Fundamentalanalyse</button>
            <button class="tab-button" onclick="openTab(event, 'depot')">Depot Status</button>
            <button class="tab-button" onclick="openTab(event, 'transaktionen')">Transaktionshistorie</button>
        </div>

        <div id="chart" class="tab-content active"></div>
        <div id="funda" class="tab-content"></div>
        <div id="depot" class="tab-content"></div>
        <div id="transaktionen" class="tab-content"></div>
    </div>

    <!-- Data Injection -->
    <script>
        const chartData = CHART_DATA_PLACEHOLDER;
        const fundaData = FUNDA_DATA_PLACEHOLDER;
        const depotData = DEPOT_DATA_PLACEHOLDER;

        function getBadge(rating) {
            const r = rating.toLowerCase();
            if (r.includes("kauf")) return `<span class="badge buy">Kaufen</span>`;
            if (r.includes("halt")) return `<span class="badge hold">Halten</span>`;
            if (r.includes("verkauf")) return `<span class="badge sell">Verkaufen</span>`;
            return `<span class="badge" style="background:#e2e3e5">${rating}</span>`;
        }

        // Render Chartanalyse
        let chartHtml = `<h2>Ergebnisse der Chartanalyse</h2><p>Übersicht der kurz-, mittel- und langfristigen Trendbewertungen.</p>`;
        for (const [sektor, werte] of Object.entries(chartData.sektoren)) {
            chartHtml += `<h3 class="sector-title">${sektor}</h3>
            <table>
                <tr>
                    <th style="width: 35%">Wertpapier</th>
                    <th style="width: 15%">Empfehlung</th>
                    <th style="width: 50%">Charttechnische Begründung</th>
                </tr>`;
            werte.forEach(w => {
                chartHtml += `<tr>
                    <td><strong>${w.wertpapier}</strong><br><small style="color: #7f8c8d;">${w.isin || ''}</small></td>
                    <td>${getBadge(w.empfehlung)}</td>
                    <td>${w.begruendung}</td>
                </tr>`;
            });
            chartHtml += `</table>`;
        }
        document.getElementById('chart').innerHTML = chartHtml;

        // Render Fundamentalanalyse
        let fundaHtml = `<h2>Ergebnisse der Fundamentalanalyse</h2><p>Vergleichende Gegenüberstellung nach der Commerzbank-Methodik.</p>`;
        for (const [sektor, werte] of Object.entries(fundaData.sektoren)) {
            fundaHtml += `<h3 class="sector-title">${sektor}</h3>
            <table>
                <tr>
                    <th>Wertpapier</th>
                    <th>KGV</th>
                    <th>KBV</th>
                    <th>KUV</th>
                    <th>KCV</th>
                    <th>Dividende</th>
                    <th>Empfehlung</th>
                    <th style="width: 35%">Begründung</th>
                </tr>`;
            werte.forEach(w => {
                fundaHtml += `<tr>
                    <td><strong>${w.wertpapier}</strong><br><small style="color: #7f8c8d;">${w.isin || ''}</small></td>
                    <td>${w.kgv}</td>
                    <td>${w.kbv}</td>
                    <td>${w.kuv}</td>
                    <td>${w.kcv}</td>
                    <td>${w.dividendenrendite}</td>
                    <td>${getBadge(w.empfehlung)}</td>
                    <td>${w.begruendung}</td>
                </tr>`;
            });
            fundaHtml += `</table>`;
        }
        document.getElementById('funda').innerHTML = fundaHtml;

        // Render Depot Status
        const d = depotData.depot;
        let depotHtml = `<h2>Aktueller Depot-Status</h2>
        
        <div class="stats-grid">
            <div class="stat-card"><h4>Gesamtvermögen</h4><p>${d.gesamtvermoegen.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</p></div>
            <div class="stat-card"><h4>Barbestand</h4><p>${d.aktueller_barbestand.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</p></div>
            <div class="stat-card"><h4>Portfoliowert</h4><p>${d.portfoliowert.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</p></div>
            <div class="stat-card"><h4>Startkapital</h4><p>${d.startkapital.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</p></div>
        </div>
        
        <h3 class="sector-title">Aktuelle Positionen (Wertpapiere)</h3>
        <table>
            <tr>
                <th>Wertpapier</th>
                <th>Stück</th>
                <th>Kaufkurs</th>
                <th>Börsenkurs</th>
                <th>Investiert</th>
                <th>Börsenwert</th>
                <th>Gewinn/Verlust</th>
            </tr>`;
        d.positionen.forEach(p => {
            let gvColor = p.gewinn_verlust >= 0 ? '#155724' : '#721c24';
            let gvBg = p.gewinn_verlust >= 0 ? '#d4edda' : '#f8d7da';
            depotHtml += `<tr>
                <td><strong>${p.wertpapier}</strong><br><small style="color: #7f8c8d;">${p.isin || ''}</small></td>
                <td>${p.stueck}</td>
                <td>${p.kaufkurs.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</td>
                <td>${(p.boersenkurs || p.kaufkurs).toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</td>
                <td>${p.investiert.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</td>
                <td>${(p.boersenwert || p.investiert).toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</td>
                <td><span style="background-color: ${gvBg}; color: ${gvColor}; padding: 4px 8px; border-radius: 4px; font-weight: bold;">${(p.gewinn_verlust || 0).toLocaleString('de-DE', {style: 'currency', currency: 'EUR', signDisplay: 'always'})}</span></td>
            </tr>`;
        });
        depotHtml += `</table>`;
        document.getElementById('depot').innerHTML = depotHtml;

        // Render Transaktionshistorie
        let transHtml = `<h2>Transaktionshistorie</h2>
        <table>
            <tr>
                <th>Datum</th>
                <th>Typ</th>
                <th>Wertpapier</th>
                <th>Stück</th>
                <th>Kurs</th>
                <th>Gebühr</th>
                <th>Steuern</th>
                <th>Gewinn/Verlust</th>
                <th>Gesamt</th>
                <th>Notiz</th>
            </tr>`;
        
        if (d.transaktionshistorie) {
            // Zeige neueste Transaktionen zuerst (optional, aber hilfreich)
            const transactionsRev = [...d.transaktionshistorie].reverse();
            transactionsRev.forEach(t => {
                let gvText = t.gewinn_verlust !== undefined ? t.gewinn_verlust.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'}) : '-';
                let steuernText = t.steuern !== undefined ? t.steuern.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'}) : '-';
                transHtml += `<tr>
                    <td>${t.datum}</td>
                    <td><strong>${t.typ}</strong></td>
                    <td><strong>${t.wertpapier}</strong><br><small style="color: #7f8c8d;">${t.isin || ''}</small></td>
                    <td>${t.stueck}</td>
                    <td>${t.kurs.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</td>
                    <td>${t.gebuehr.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</td>
                    <td>${steuernText}</td>
                    <td>${gvText}</td>
                    <td>${t.gesamt.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'})}</td>
                    <td><small>${t.notiz || ''}</small></td>
                </tr>`;
            });
        }
        transHtml += `</table>`;
        document.getElementById('transaktionen').innerHTML = transHtml;


        // Tab Logic
        function openTab(evt, tabName) {
            const tabcontent = document.getElementsByClassName("tab-content");
            for (let i = 0; i < tabcontent.length; i++) {
                tabcontent[i].classList.remove("active");
            }
            const tablinks = document.getElementsByClassName("tab-button");
            for (let i = 0; i < tablinks.length; i++) {
                tablinks[i].classList.remove("active");
            }
            document.getElementById(tabName).classList.add("active");
            evt.currentTarget.classList.add("active");
        }
    </script>
</body>
</html>"""

# Replace placeholders
html_output = html_template.replace("CHART_DATA_PLACEHOLDER", chart_data)
html_output = html_output.replace("FUNDA_DATA_PLACEHOLDER", funda_data)
html_output = html_output.replace("DEPOT_DATA_PLACEHOLDER", depot_data)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html_output)

print("Dashboard erfolgreich aktualisiert: index.html")
