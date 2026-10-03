#!/usr/bin/env python
"""
tests/voir_prompt.py

StatSense AI — Ce que le modèle reçoit et produit, exactement.

    backend/.venv/bin/python tests/voir_prompt.py "votre question"

Affiche les quatre étapes qui entourent l'unique appel au modèle : les
candidats retenus par la recherche, le prompt envoyé mot pour mot, la
réponse brute, puis le plan après correction et validation.

Sert à comprendre, à déboguer une question qui tombe à côté, et à
montrer à un évaluateur que le modèle ne reçoit aucun chiffre.
"""

import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()

from ai.client import client, extraire_json  # noqa: E402
from ai.plan import valider  # noqa: E402
from ai.prompts import SYSTEME_EXTRACTION, prompt_extraction  # noqa: E402
from ai.recherche import fiches, mots_utiles, rechercher, zones_connues  # noqa: E402
from ai.zones import corriger_zones, zones_citees  # noqa: E402

question = " ".join(sys.argv[1:]) or "Quelles sont les 5 régions les plus peuplées ?"


def titre(n, texte):
    print(f"\n{'─' * 72}\n  {n}. {texte}\n{'─' * 72}")


print(f"\n  QUESTION : {question}")

# ---------------------------------------------------------------------------
titre(1, "RECHERCHE DANS LE CATALOGUE  (PostgreSQL, sans modèle)")

print(f"  mots retenus : {mots_utiles(question)}")
candidats = rechercher(question)
print(f"\n  {len(candidats)} indicateur(s) candidat(s) :")
for i in candidats:
    print(f"    · {i.code:22} {i.libelle}")

if not candidats:
    print("\n  Aucun candidat : le modèle ne sera pas appelé.")
    sys.exit(0)

# ---------------------------------------------------------------------------
titre(2, "PROMPT ENVOYÉ AU MODÈLE  (mot pour mot)")

prompt = prompt_extraction(question, fiches(candidats), zones_connues())
print(f"\n[système]\n{SYSTEME_EXTRACTION}\n")
print(f"[utilisateur]\n{prompt}")

print(f"\n  → {len(prompt)} caractères, environ {len(prompt) // 4} tokens.")
print("  → Aucune observation, aucune valeur chiffrée : uniquement des")
print("    métadonnées d'indicateurs.")

# ---------------------------------------------------------------------------
titre(3, "RÉPONSE BRUTE DU MODÈLE")

c = client()
if not c.disponible():
    print("  Modèle injoignable — lancez `ollama serve`.")
    sys.exit(1)

debut = time.perf_counter()
brut = c.completer(prompt, systeme=SYSTEME_EXTRACTION, json_attendu=True,
                   max_tokens=300, temperature=0.1)
duree = time.perf_counter() - debut

print(f"\n{brut}\n")
print(f"  → {duree:.1f}s, environ {len(brut) // 4} tokens produits.")

# ---------------------------------------------------------------------------
titre(4, "APRÈS CORRECTION ET VALIDATION  (code déterministe)")

plan = valider(extraire_json(brut))
avant = list(plan.get("zones") or [])
plan = corriger_zones(plan, question)

print(f"  zones proposées par le modèle : {avant}")
print(f"  zones reconnues dans la question : {zones_citees(question)}")
print(f"  zones retenues : {plan['zones']}")

print("\n  Plan final :")
for cle in ("methode", "indicateur", "zones", "niveau", "periode",
            "filtres", "dimension", "top_n", "ordre", "confiance"):
    if cle in plan:
        print(f"    {cle:14} {plan[cle]}")

print("\n  C'est ce plan, et lui seul, qui part au moteur de calcul.")
print("  Le modèle n'intervient plus au-delà de ce point.\n")