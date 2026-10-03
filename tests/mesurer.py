"""
tests/mesurer.py

StatSense AI — Coût réel d'un appel au modèle, selon la taille du prompt

À lancer ainsi, depuis la racine du projet :

    backend/.venv/bin/python backend/manage.py shell < tests/mesurer.py

Ce script ne modifie rien. Il construit le VRAI prompt d'extraction, tel
que `chaine.py` l'envoie, puis le soumet à Ollama en trois variantes :
catalogue entier, six fiches, trois fiches. Pour chacune il relève les
compteurs que renvoie Ollama — nombre de tokens lus, nombre de tokens
générés, et le temps de chacun.

Pourquoi c'est nécessaire : une mesure prise sur un prompt de quelques
dizaines de tokens ne dit rien du débit de lecture, parce qu'elle est
dominée par le coût fixe de l'appel. Seul un prompt de taille réelle
donne le chiffre utile.

Ce qu'on cherche à savoir :

  - quelle part des 160 s vient de la LECTURE du prompt et quelle part
    de la GÉNÉRATION du plan ;
  - combien on gagne en n'envoyant que les candidats plausibles au lieu
    du catalogue entier ;
  - si l'indicateur choisi reste le bon quand la liste rétrécit — un
    gain de latence qui dégrade la justesse ne vaut rien.

Compter une dizaine de minutes : six appels réels, sans cache.
"""

import time

import requests
from django.conf import settings

from ai.prompts import SYSTEME_EXTRACTION, prompt_extraction
from ai.recherche import fiches, rechercher, zones_connues

# Deux questions représentatives : une simple, une qui demande un
# classement sur un indicateur dérivé.
QUESTIONS = [
    ("Combien d'habitants compte la région de Thiès ?", "pop_totale"),
    ("Quel est le taux de natalité par région ?", "taux_natalite"),
]

# Nombre de fiches envoyées dans chaque variante. None = toutes.
VARIANTES = [None, 6, 3]

HOTE = getattr(settings, "OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODELE = getattr(settings, "OLLAMA_MODEL", "qwen2.5:3b-instruct")


def appeler(prompt):
    """Un appel identique à celui de client.py, compteurs relevés."""
    charge = {
        "model": MODELE,
        "prompt": prompt,
        "system": SYSTEME_EXTRACTION,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_predict": 300,
            "top_p": 0.9,
            "repeat_penalty": 1.05,
        },
        "keep_alive": -1,
    }
    debut = time.perf_counter()
    r = requests.post(f"{HOTE}/api/generate", json=charge, timeout=900)
    mur = time.perf_counter() - debut
    r.raise_for_status()
    return r.json(), mur


def secondes(d, cle):
    return max(d.get(cle) or 0, 1) / 1e9


def main():
    print()
    print("=" * 78)
    print("  COÛT D'UN APPEL SELON LA TAILLE DU PROMPT")
    print("=" * 78)

    total_candidats = len(rechercher(QUESTIONS[0][0]))
    print(f"\n  Catalogue envoyé aujourd'hui : {total_candidats} fiches")
    print(f"  Modèle : {MODELE}")
    print(f"  Hôte   : {HOTE}")

    for question, attendu in QUESTIONS:
        candidats = rechercher(question)
        print()
        print("-" * 78)
        print(f"  {question}")
        print(f"  attendu : {attendu}")
        print("-" * 78)
        print(f"  {'fiches':>7}  {'prompt':>7}  {'lecture':>9}  "
              f"{'sortie':>6}  {'génère':>9}  {'total':>7}   indicateur")

        for n in VARIANTES:
            sous = candidats if n is None else candidats[:n]
            prompt = prompt_extraction(question, fiches(sous),
                                       zones_connues())
            try:
                d, mur = appeler(prompt)
            except Exception as e:
                print(f"  {len(sous):>7}  échec : {e}")
                continue

            pe = d.get("prompt_eval_count", 0)
            ped = secondes(d, "prompt_eval_duration")
            ec = d.get("eval_count", 0)
            ed = secondes(d, "eval_duration")

            # L'indicateur produit, pour vérifier que réduire la liste
            # ne change pas la réponse.
            try:
                import json as _j
                obj = _j.loads(d.get("response") or "{}")
                ind = str(obj.get("indicateur") or "—")
            except Exception:
                ind = "illisible"

            marque = "OK" if attendu in ind else "!!"
            print(f"  {len(sous):>7}  {pe:>7}  "
                  f"{ped:>6.1f}s {pe/ped:>5.0f}/s  "
                  f"{ec:>6}  {ed:>6.1f}s {ec/ed:>4.1f}/s  "
                  f"{mur:>6.1f}s   {ind} {marque}")

    print()
    print("=" * 78)
    print("  LECTURE DU TABLEAU")
    print("=" * 78)
    print("""
  La colonne « lecture » donne le débit réel en tokens/s sur un prompt
  de taille réaliste. C'est le chiffre qui manquait.

  Si le temps de lecture domine le total, alors réduire le nombre de
  fiches est le levier principal, et CATALOGUE_COMPLET_MAX doit
  descendre de 25 à 6.

  Si c'est la génération qui domine, la taille du prompt n'y changera
  rien et seule une machine plus rapide — ou un plan plus court à
  produire — fera une différence.

  Dans les deux cas, regarde la dernière colonne avant de conclure :
  si l'indicateur devient faux à 3 fiches, le plancher est à 6.
""")


main()