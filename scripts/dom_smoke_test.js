// DOM-Smoke-Test für das Dashboard: lädt index.html in jsdom mit einem
// fetch-Shim (liest data/*.json von Platte) und prüft, dass alle Sektionen
// tatsächlich rendern. Fängt Laufzeitfehler (z.B. TDZ/Reihenfolge-Bugs),
// die `node --check` nicht sieht — der 09:00-Lauf testet nur Python.
//
// Aufruf:  node scripts/dom_smoke_test.js
// Voraussetzung: jsdom auffindbar (z.B. npm install --prefix ~/.dashtest jsdom
// und NODE_PATH=~/.dashtest/node_modules, oder Pfad unten anpassen).
const fs = require('fs');
const path = require('path');

let JSDOM;
const candidates = [
    'jsdom',
    path.join(process.env.HOME || '', '.dashtest', 'node_modules', 'jsdom'),
];
for (const c of candidates) {
    try { ({ JSDOM } = require(c)); break; } catch (e) { /* nächster Kandidat */ }
}
if (!JSDOM) {
    console.error('jsdom nicht gefunden — npm install --prefix ~/.dashtest jsdom');
    process.exit(2);
}

const repo = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(repo, 'index.html'), 'utf8');

const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'http://localhost/',
    beforeParse(window) {
        window.fetch = async (url) => {
            const rel = url.split('?')[0];
            try {
                const body = fs.readFileSync(path.join(repo, rel), 'utf8');
                return { ok: true, json: async () => JSON.parse(body) };
            } catch (e) {
                return { ok: false, json: async () => null };
            }
        };
        window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
    },
});

setTimeout(() => {
    const doc = dom.window.document;
    const anzahlPositionen = JSON.parse(
        fs.readFileSync(path.join(repo, 'data', 'depot_status.json'), 'utf8')
    ).depot.positionen.length;
    const checks = {
        'V1 Equity-SVG vorhanden': !!doc.getElementById('eq-svg'),
        'V1 Legende gefüllt': doc.querySelectorAll('.eq-legend > span').length >= 3,
        'V3 Frische-Badges (6 Quellen)': doc.querySelectorAll('#fresh-row .fresh-badge').length === 6,
        'V2 Stop-Spalte im Depot': doc.body.innerHTML.includes('Stop-Abstand'),
        'V2 Ampel-Badge je Position': [...doc.querySelectorAll('#depot td')]
            .filter(td => /🟢|🟡|🔴/.test(td.textContent)).length === anzahlPositionen,
        'V4 Kosten-Tabelle': doc.body.innerHTML.includes('Handelsaktivität'),
        'V5 Attribution gerendert': (doc.getElementById('attribution').textContent || '').length > 200,
        'V6 Signal-Monitor': (doc.getElementById('attribution').textContent || '').includes('Signal-Monitor'),
        'Übersicht nicht leer': (doc.getElementById('uebersicht').textContent || '').length > 500,
        'Empfehlungs-Ranking gerendert': (doc.getElementById('ranking').textContent || '').length > 200,
    };
    let fail = 0;
    for (const [k, v] of Object.entries(checks)) {
        console.log((v ? '✓' : '✗') + ' ' + k);
        if (!v) fail++;
    }
    process.exit(fail ? 1 : 0);
}, 600);
