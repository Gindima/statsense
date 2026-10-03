#!/usr/bin/env python
"""
StatSense AI — Vérification de la chaîne complète.

    backend/.venv/bin/python tests/test_chaine.py

Mesure trois choses :
  - le taux de plans valides produits par le modèle (seuil : 70 %)
  - le bon fonctionnement des refus (exigence : 100 %, ils ne dépendent
    pas du modèle mais de la validation)
  - la latence de bout en bout
"""

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()

from ai.chaine import repondre  # noqa: E402
from ai.client import client  # noqa: E402

REUSSITES = [
    ("Quelles sont les 5 régions les plus peuplées ?", "classement"),
    ("Combien d'habitants compte la région de Thiès ?", "valeur_simple"),
    ("Combien de ménages y a-t-il à Diourbel ?", "valeur_simple"),
    ("Où les ménages sont-ils les plus grands ?", "classement"),
    ("Montre-moi l'accès à l'électricité sur une carte", "geographique"),
    ("Carte de la population par région", "geographique"),
    ("Comment le chômage a-t-il évolué au Sénégal ?", "evolution"),
    ("Évolution de la population de Dakar", "evolution"),
    ("Quelles régions sont les moins peuplées ?", "classement"),
    ("Quel est le taux de chômage actuel ?", "valeur_simple"),
]

REFUS = [
    "Quel est le taux d'alphabétisation par région ?",
    "Quelle était la population de Dakar en 2010 ?",
]

CLARIFICATIONS = [
    "Combien de gens ?",
]

c = client()
print(f"\n  Modèle : {c.modele}   disponible : {c.disponible()}\n")

bons = plans_ok = 0
latences = []

print("  — Questions devant aboutir —")
for question, methode_attendue in REUSSITES:
    r = repondre(question)
    statut = r["statut"]
    plan = r.get("plan") or {}
    ok_methode = plan.get("methode") == methode_attendue
    plans_ok += int(ok_methode)
    d = (r.get("meta") or {}).get("duree_s")
    if d:
        latences.append(d)

    if statut == "ok":
        bons += 1
        marque = "✓" if ok_methode else "~"
        n = len(r["resultat"]["lignes"])
        org = (r["meta"].get("narration") or {}).get("origine", "?")
        print(f"  {marque} {question[:46]:48} {plan.get('methode','?'):14}"
              f" {n:3} ligne(s)  {d}s  texte:{org}")
        print(f"      {r['texte'][:120]}")
    else:
        print(f"  ✗ {question[:46]:48} {statut} — {r.get('message','')[:60]}")

print("\n  — Questions devant être refusées —")
refus_ok = 0
for question in REFUS:
    r = repondre(question)
    if r["statut"] == "refus":
        refus_ok += 1
        print(f"  ✓ {question[:46]:48} [{r['motif']}]")
        print(f"      {r['message'][:110]}")
    else:
        print(f"  ✗ {question[:46]:48} aurait dû être refusée ({r['statut']})")

print("\n  — Questions devant demander une précision —")
clar_ok = 0
for question in CLARIFICATIONS:
    r = repondre(question)
    if r["statut"] == "clarification":
        clar_ok += 1
        print(f"  ✓ {question[:46]:48} {r['message'][:60]}")
    else:
        print(f"  ✗ {question[:46]:48} {r['statut']}")

total = len(REUSSITES)
print(f"\n  Plans corrects       : {plans_ok}/{total} "
      f"({plans_ok / total * 100:.0f} %)   seuil 70 %")
print(f"  Réponses abouties    : {bons}/{total}")
print(f"  Refus corrects       : {refus_ok}/{len(REFUS)}   exigence 100 %")
print(f"  Clarifications       : {clar_ok}/{len(CLARIFICATIONS)}")
if latences:
    print(f"  Latence médiane      : "
          f"{sorted(latences)[len(latences) // 2]}s")