#!/usr/bin/env python
"""
tests/prechauffer.py

StatSense AI — Préchauffage du cache de démonstration

    backend/.venv/bin/python tests/prechauffer.py

Exécute les questions de démonstration et les épingle en cache. Elles
répondront ensuite instantanément, et de façon identique à chaque
répétition — ce qui est précisément ce qu'on veut devant un jury.

À relancer après chaque `make seed`, puisque le rechargement des données
peut changer les résultats, et après toute modification du moteur ou de la
sélection d'indicateurs.


POURQUOI LE SCRIPT VÉRIFIE LE MODÈLE AVANT DE COMMENCER

Constaté une fois, et le dégât n'était pas visible dans la sortie :

    Modèle indisponible (port 11434, connection refused), repli déterministe
    ✓ 10. Quel est le taux de natalité par région ?   valeur_simple  1 ligne

Ollama était arrêté. Les dix questions sont passées par le repli
déterministe, et leurs réponses dégradées ont été épinglées. La dixième
rendait une seule valeur là où la même question, posée avec le modèle,
rend les quatorze régions. Le cache portait donc une mauvaise réponse,
marquée comme bonne, prête à sortir devant un jury.

Les coches vertes ne mentaient pas : la chaîne avait bien répondu. Elles
ne disaient simplement pas PAR QUI.

Deux garde-fous en découlent, et c'est tout l'objet de cette version :

    1. le modèle est vérifié avant la première question ; s'il manque, le
       script s'arrête sans rien écrire ;

    2. aucune réponse dont l'origine est `repli` ou `echec` n'est épinglée,
       même si le modèle était là au départ et a disparu en cours de route.

Un préchauffage qui mémorise des réponses de repli est pire que pas de
préchauffage : il remplace une lenteur visible par une erreur invisible.


CODE DE SORTIE

Non nul si le modèle est injoignable ou si une réponse est venue du repli.

Un refus ou une clarification ne font PAS échouer le script : ce sont des
réponses légitimes, et certaines questions de la liste sont là pour les
produire. Ce que le code de sortie contrôle, c'est que le modèle a bien
servi chaque question — pas que chaque question avait une réponse.
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

from django.conf import settings  # noqa: E402

from ai.chaine import repondre  # noqa: E402
from api import cache  # noqa: E402
from api.models import Requete  # noqa: E402

# Origines qui signalent une réponse produite sans le modèle. Voir
# ai/chaine.py : `repli` vient d'un modèle injoignable, `echec` de deux
# réponses inexploitables de suite.
ORIGINES_DEGRADEES = {"repli", "echec"}

# Questions de la démonstration, dans l'ordre de présentation.
DEMO = [
    # --- ouverture : des chiffres simples, vérifiables de tête ---
    "Combien d'habitants compte la région de Thiès ?",
    "Combien de ménages y a-t-il à Diourbel ?",

    # --- classements et cartes : ce qui se montre bien à l'écran ---
    "Quelles sont les 5 régions les plus peuplées ?",
    "Quelles régions sont les moins peuplées ?",
    "Où les ménages sont-ils les plus grands ?",
    "Taux de natalité des 14 régions du Sénégal",
    "Montre-moi l'accès à l'électricité sur une carte",
    "Carte de la population par région",

    # --- séries temporelles, de la plus courte à la plus profonde ---
    "Évolution de la population de Dakar",
    "Comment le chômage a-t-il évolué au Sénégal ?",
    "Comment l'accès à l'eau a-t-il évolué à Kolda ?",

    # --- le relais entre séries : la note explique la substitution ---
    "Évolution de la population sénégalaise entre 2010 et 2025",

    # --- ventilation par âge ---
    "Quelle est la répartition de la population par tranche d'âge ?",

    # --- question documentaire : répond sans appeler le modèle ---
    "Quand a eu lieu le dernier recensement ?",

    # --- refus méthodologiques : ce qui distingue la plateforme d'un
    #     agent conversationnel branché sur un tableur ---
    "Quel est le taux de chômage à Mbour ?",
    "Quelle était la population de Dakar en 2010 ?",
    "Quel est le PIB du Sénégal ?",
]


def _hote_et_modele():
    hote = getattr(settings, "OLLAMA_HOST", None) \
        or os.getenv("OLLAMA_HOST", "http://localhost:11434")
    modele = getattr(settings, "OLLAMA_MODEL", None) \
        or os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct")
    return hote.rstrip("/"), modele


def verifier_modele():
    """
    Le modèle est-il joignable et chargé ?

    Vérifié AVANT la première question, parce qu'un modèle absent ne fait
    pas échouer la chaîne : elle se replie, répond, et le préchauffage
    épinglerait ces réponses-là.
    """
    import requests

    hote, modele = _hote_et_modele()
    try:
        r = requests.get(f"{hote}/api/tags", timeout=5)
        noms = [m["name"] for m in r.json().get("models", [])]
    except Exception as e:
        return False, (f"{hote} injoignable ({e.__class__.__name__}). "
                       f"Démarrer Ollama avant de préchauffer.")

    if not any(n.startswith(modele.split(":")[0]) for n in noms):
        return False, (f"{modele} absent de {hote}. "
                       f"Modèles présents : {noms or 'aucun'}.")
    return True, f"{modele} disponible sur {hote}"


def purger():
    """
    Retire les réponses épinglées, et les entrées de cache ordinaires des
    questions de la liste.

    Les deux : une entrée non épinglée de la même question pourrait sortir
    à la place de celle qu'on vient d'écrire, et masquer une correction du
    moteur par une réponse d'avant.
    """
    n = Requete.objects.filter(epingle=True).delete()[0]
    try:
        n += Requete.objects.filter(question__in=DEMO).delete()[0]
    except Exception:
        # Le champ ne s'appelle pas `question` dans ce modèle : on se
        # contente des épinglées, et on le dit.
        print("  ⚠ purge limitée aux réponses épinglées")
    return n


# --- exécution -------------------------------------------------------------

print()
disponible, detail = verifier_modele()
print(f"  {detail}")
if not disponible:
    print("\n  ✗ Préchauffage abandonné : rien n'a été écrit en cache.\n")
    sys.exit(1)

print(f"\n  Préchauffage de {len(DEMO)} questions\n")
print(f"  {purger()} entrée(s) de cache retirée(s)\n")

epinglees = refus = degradees = 0
debut_total = time.perf_counter()

for i, question in enumerate(DEMO, 1):
    debut = time.perf_counter()
    r = repondre(question)
    duree = time.perf_counter() - debut

    origine = (r.get("meta") or {}).get("origine")
    etiquette = f"{i:2}. {question[:52]:54}"

    # 1. Réponse produite sans le modèle : on ne l'épingle pas.
    if origine in ORIGINES_DEGRADEES:
        degradees += 1
        print(f"  ✗ {etiquette} ORIGINE « {origine} » — non épinglée")
        continue

    # 2. Réponse documentaire : pas de cache à constituer, elle ne passe
    #    pas par le modèle et sort déjà en zéro seconde.
    if origine == "documentaire":
        print(f"  · {etiquette} documentaire          {duree:.1f}s")
        continue

    # 3. Réponse chiffrée : c'est celle qu'on épingle.
    if r["statut"] == "ok":
        cache.ecrire(question, r, epingle=True)
        epinglees += 1
        res = r["resultat"]
        relais = (res.get("meta") or {}).get("serie_relais")
        marque = f" [relais -> {relais}]" if relais else ""
        print(f"  ✓ {etiquette} {r['plan']['methode']:14} "
              f"{len(res['lignes']):3} ligne(s)  {duree:.1f}s{marque}")
        continue

    # 4. Refus ou clarification : attendu pour une partie de la liste.
    refus += 1
    print(f"  – {etiquette} {r['statut']:14} "
          f"{r.get('motif') or '':24} {duree:.1f}s")

total = time.perf_counter() - debut_total

print()
print(f"  {epinglees} épinglée(s), {refus} refus ou clarification(s), "
      f"{degradees} dégradée(s) — {total:.0f}s")

if degradees:
    print(f"\n  ✗ {degradees} réponse(s) produite(s) sans le modèle et donc "
          f"écartée(s).")
    print("    Vérifier Ollama, puis relancer : le cache est incomplet.\n")
    sys.exit(1)

print("  Les questions épinglées répondent maintenant instantanément.\n")