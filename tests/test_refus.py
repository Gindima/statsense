#!/usr/bin/env python
"""
tests/test_refus.py

StatSense AI — Fiabilité des refus, mesurée sur plusieurs passages.

    backend/.venv/bin/python tests/test_refus.py [répétitions]

Un test unique ne dit rien d'un système probabiliste : le même cas peut
passer puis échouer. Ce script rejoue les seuls cas de refus, sans
cache, et rapporte un taux.

Les cas ne se valent pas :

  - période hors couverture, ventilation indisponible, granularité
    insuffisante : une fois l'indicateur choisi, la validation tranche.
    Ces refus ne dépendent pas du modèle et doivent être constants.

  - indicateur absent du catalogue : le modèle peut substituer un
    indicateur existant au lieu de renvoyer null. Ce refus dépend de
    lui, et c'est celui qu'un exemple dans le prompt améliore.
"""

import os
import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()

from ai.chaine import repondre  # noqa: E402

REPETITIONS = int(sys.argv[1]) if len(sys.argv) > 1 else 3

CAS = [
    ("Quel est le taux d'alphabétisation par région ?",
     "indicateur_absent", "dépend du modèle"),
    ("Quelle était la population de Dakar en 2010 ?",
     "periode_non_couverte", "déterministe"),
    ("Combien de ménages dirigés par une femme à Dakar ?",
     "dimension_invalide", "déterministe"),
]

print(f"\n  {REPETITIONS} passage(s) sur {len(CAS)} cas de refus\n")

resultats = {q: Counter() for q, _, _ in CAS}

for tour in range(1, REPETITIONS + 1):
    print(f"  — passage {tour} —")
    for question, motif_attendu, nature in CAS:
        r = repondre(question)
        statut = r["statut"]
        motif = r.get("motif", "")

        if statut == "refus" and motif == motif_attendu:
            issue, marque = "correct", "✓"
        elif statut == "refus":
            issue, marque = f"autre motif ({motif})", "~"
        elif statut == "clarification":
            issue, marque = "clarification", "~"
        else:
            ind = (r.get("plan") or {}).get("indicateur")
            issue, marque = f"a répondu avec {ind}", "✗"

        resultats[question][issue] += 1
        print(f"    {marque} {question[:44]:46} {issue}")
    print()

print(f"  {'─' * 70}")
for question, motif, nature in CAS:
    c = resultats[question]
    taux = c["correct"] / REPETITIONS * 100
    print(f"\n  {question}")
    print(f"    attendu : {motif}  ({nature})")
    print(f"    {taux:.0f} % de refus corrects sur {REPETITIONS} passages")
    for issue, n in c.most_common():
        if issue != "correct":
            print(f"      · {n}× {issue}")

total = sum(c["correct"] for c in resultats.values())
sur = len(CAS) * REPETITIONS
print(f"\n  Total : {total}/{sur} ({total / sur * 100:.0f} %)\n")

if total < sur:
    print("  Un refus qui varie d'un passage à l'autre est un refus qui")
    print("  peut manquer devant le jury. Renforcez l'exemple correspondant")
    print("  dans le prompt, ou déplacez la vérification dans le code.\n")