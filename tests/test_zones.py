#!/usr/bin/env python
"""
tests/test_zones.py

StatSense AI — Vérification de la reconnaissance des zones.

    backend/.venv/bin/python tests/test_zones.py

Ne touche ni au modèle ni à la base de résultats : mesure uniquement si
les zones citées dans une question sont correctement repérées. Trente
secondes, et le doute est levé.
"""

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()

from ai.zones import zones_citees  # noqa: E402

CAS = [
    # --- formulations courantes ---
    ("Combien d'habitants à Kaolack ?", ["KAOLACK"]),
    ("Combien d'habitants compte la région de Thiès ?", ["THIES"]),
    ("Quelle est la population de Diourbel ?", ["DIOURBEL"]),
    ("Population de Kédougou", ["KEDOUGOU"]),
    ("Combien de ménages à Ziguinchor ?", ["ZIGUINCHOR"]),

    # --- accents et tirets absents ---
    ("Population de Thies", ["THIES"]),
    ("Habitants de Kedougou", ["KEDOUGOU"]),
    ("Population de Saint Louis", ["SAINT-LOUIS"]),
    ("Population de Saint-Louis", ["SAINT-LOUIS"]),

    # --- noms composés ---
    ("Combien d'habitants à Keur Massar ?", ["KEUR MASSAR"]),
    ("Population de Guédiawaye", ["GUEDIAWAYE"]),

    # --- national ---
    ("Comment le chômage a-t-il évolué au Sénégal ?", ["SENEGAL"]),
    ("Taux de natalité au niveau national", ["SENEGAL"]),

    # --- deux zones ---
    ("Compare Dakar et Thiès", ["DAKAR", "THIES"]),

    # --- aucune zone : ne doit RIEN inventer ---
    ("Quelles sont les 5 régions les plus peuplées ?", []),
    ("Où les ménages sont-ils les plus grands ?", []),
    ("Carte de la population par région", []),
]

ok = ko = 0
for question, attendu in CAS:
    trouve = zones_citees(question)
    if trouve == attendu:
        ok += 1
        print(f"  ✓ {question[:46]:48} {trouve}")
    else:
        ko += 1
        print(f"  ✗ {question[:46]:48} {trouve}  (attendu {attendu})")

print(f"\n  {ok}/{len(CAS)} correct")
if ko:
    print("  Les cas en échec sont à corriger avant d'activer corriger_zones.")
sys.exit(0 if ko == 0 else 1)