"""Tests für den Chart/Funda-Sanity-Check (consistency.py) — muss synchron zu
dataConsistency() im Dashboard bleiben, sonst handelt die Engine andere Daten,
als das Dashboard anzeigt (Ursache des Engine/Dashboard-Drift-Bugs)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from consistency import data_consistency


class TestDataConsistency(unittest.TestCase):
    def test_saubere_daten_keine_warnung(self):
        chart = {"aktueller_kurs": 100, "sma_50": 98, "sma_200": 95,
                 "unterstuetzung": 90, "widerstand": 110, "trend": "Seitwärts"}
        self.assertEqual(data_consistency(chart, {}), [])

    def test_sma50_weit_weg_warnt(self):
        chart = {"aktueller_kurs": 100, "sma_50": 60}
        warnings = data_consistency(chart, {})
        self.assertTrue(any("SMA50" in w for w in warnings))

    def test_sma200_gelockert_bei_bestaetigtem_aufwaertstrend(self):
        # Kurs > SMA50 > SMA200 + Aufwärtstrend: 50% Abstand zum SMA200 ist ok
        chart = {"aktueller_kurs": 150, "sma_50": 130, "sma_200": 100,
                 "trend": "Aufwärts"}
        warnings = data_consistency(chart, {})
        self.assertFalse(any("SMA200" in w for w in warnings))

    def test_aufwaertstrend_mit_kurs_unter_sma50_warnt(self):
        chart = {"aktueller_kurs": 80, "sma_50": 100, "trend": "Aufwärtstrend"}
        warnings = data_consistency(chart, {})
        self.assertTrue(any("Aufwärtstrend" in w for w in warnings))

    def test_negative_begruendung_bei_kaufsignal_warnt(self):
        chart = {"empfehlung": "Kaufen",
                 "begruendung": "Kurs im Sinkflug ohne Bodenbildung."}
        warnings = data_consistency(chart, {})
        self.assertTrue(any("negativ" in w for w in warnings))

    def test_verkaufssignal_triggert_keine_kaufsignal_warnung(self):
        # Regression: "kauf" in "Verkaufen" (Teilstring) darf nicht matchen
        chart = {"empfehlung": "Verkaufen",
                 "begruendung": "Kurs im Sinkflug ohne Bodenbildung."}
        warnings = data_consistency(chart, {})
        self.assertFalse(any("negativ" in w for w in warnings))

    def test_relativierter_negativsatz_zaehlt_nicht(self):
        chart = {"empfehlung": "Kaufen",
                 "begruendung": "Nach schwachem Vorjahr deutliche Erholung."}
        self.assertEqual(data_consistency(chart, {}), [])

    def test_none_inputs(self):
        self.assertEqual(data_consistency(None, None), [])


if __name__ == "__main__":
    unittest.main()
