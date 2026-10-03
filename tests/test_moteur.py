#!/usr/bin/env python
"""
StatSense AI — Vérification du moteur analytique sur les données chargées.

    python backend/manage.py shell < tests/test_moteur.py

Ou en autonome :
    python tests/test_moteur.py
"""

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()

from analytics.moteur import executer
from analytics.resultats import ErreurAnalyse

CAS = [
    # --- doivent réussir ---
    ("vs01", {"methode": "valeur_simple", "indicateur": "pop_totale",
              "zones": ["DAKAR"], "niveau": "region"}, True),
    ("vs02", {"methode": "valeur_simple", "indicateur": "menages",
              "zones": ["DIOURBEL"], "niveau": "region"}, True),
    ("vs03", {"methode": "valeur_simple", "indicateur": "taille_menage",
              "zones": ["DAKAR"], "niveau": "region"}, True),
    ("cl01", {"methode": "classement", "indicateur": "pop_totale",
              "niveau": "region", "top_n": 5, "ordre": "desc"}, True),
    ("cl02", {"methode": "classement", "indicateur": "pop_totale",
              "niveau": "departement", "zones": ["DAKAR"], "top_n": 5}, True),
    ("cl03", {"methode": "classement", "indicateur": "taille_menage",
              "niveau": "region", "top_n": 5}, True),
    ("ev01", {"methode": "evolution", "indicateur": "pop_region",
              "zones": ["DAKAR"]}, True),
    ("ev02", {"methode": "evolution", "indicateur": "taux_chomage_a",
              "zones": ["SENEGAL"]}, True),
    ("ge01", {"methode": "geographique", "indicateur": "pop_totale",
              "niveau": "region"}, True),
    ("ge02", {"methode": "geographique", "indicateur": "acces_electricite",
              "niveau": "region"}, True),

    # --- doivent échouer proprement ---
    ("rf01", {"methode": "valeur_simple", "indicateur": "taux_chomage_a",
              "zones": ["DAKAR"], "niveau": "quartier"}, False),
    ("rf02", {"methode": "valeur_simple", "indicateur": "pop_totale",
              "zones": ["DAKAR"], "niveau": "region",
              "periode": {"fin": 2010}}, False),
    ("rf03", {"methode": "valeur_simple", "indicateur": "taux_alphabetisation",
              "zones": ["DAKAR"]}, False),
    ("rf04", {"methode": "valeur_simple", "indicateur": "menages",
              "zones": ["DAKAR"], "filtres": {"sexe": "F"}}, False),
]

ok = ko = 0
for ident, plan, doit_reussir in CAS:
    try:
        r = executer(plan)
        if doit_reussir:
            ok += 1
            tete = r.lignes[0] if r.lignes else {}
            apercu = tete.get("valeur", "-")
            print(f"  ✓ {ident}  {r.chart_hint:11} {len(r.lignes):3} ligne(s)"
                  f"  première valeur={apercu} {r.unite}")
            for n in r.notes:
                print(f"       note: {n}")
        else:
            ko += 1
            print(f"  ✗ {ident}  aurait dû échouer, a réussi")
    except ErreurAnalyse as e:
        if doit_reussir:
            ko += 1
            print(f"  ✗ {ident}  échec inattendu : {e.message}")
        else:
            ok += 1
            print(f"  ✓ {ident}  refus correct [{e.motif}] : {e.message}")
    except Exception as e:
        ko += 1
        print(f"  ✗ {ident}  erreur technique : {type(e).__name__}: {e}")

print(f"\n  {ok} réussis, {ko} échoués sur {len(CAS)} cas")
sys.exit(0 if ko == 0 else 1)