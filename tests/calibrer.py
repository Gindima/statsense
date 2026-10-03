"""
tests/calibrer.py

StatSense AI — Mesure de l'appariement question → indicateur

À lancer ainsi, depuis la racine du projet :

    backend/.venv/bin/python backend/manage.py shell < tests/calibrer.py

Ce script ne modifie rien. Il compare deux façons de mesurer la
proximité entre un mot de la question et la fiche d'un indicateur :

  similarity(fiche, mot)        — ce que fait recherche.py aujourd'hui
  word_similarity(mot, fiche)   — ce qu'il devrait faire

La différence n'est pas un détail d'implémentation. similarity() est
symétrique : elle divise les trigrammes communs par le total des
trigrammes des DEUX chaînes. Un mot de huit lettres comparé à une fiche
de deux cents caractères plafonne mécaniquement bas, même quand la
correspondance est exacte. Plus un indicateur est bien documenté, plus
son score baisse — le catalogue punit le soin qu'on y met.

word_similarity(mot, fiche) est asymétrique : elle cherche dans la
fiche le meilleur fragment aligné sur des frontières de mots et ne note
que celui-là. La longueur de la fiche cesse de compter.

Lis la sortie de bas en haut : la dernière section donne les seuils à
inscrire dans recherche.py et plan.py, calculés sur tes données.
"""

import re
import unicodedata

from catalog.models import Indicateur
from django.db import connection

# ---------------------------------------------------------------------
# Questions de contrôle. Les six premières doivent trouver un
# indicateur ; les trois dernières doivent être refusées, et servent à
# fixer le plancher : aucun seuil ne doit les laisser passer.
# ---------------------------------------------------------------------

DOIVENT_TROUVER = [
    ("Quelles sont les 5 régions les plus peuplées ?", "pop_totale"),
    ("Combien d'habitants compte la région de Thiès ?", "pop_totale"),
    ("Où les ménages sont-ils les plus grands ?", "taille_menage"),
    ("Montre-moi l'accès à l'électricité sur une carte", "acces_electricite"),
    ("Comment le chômage a-t-il évolué au Sénégal ?", "taux_chomage_a"),
    ("Combien de ménages y a-t-il à Diourbel ?", "menages"),
    ("Quel est le taux de natalité par région ?", "taux_natalite"),
    ("Carte de la population par région", "pop_totale"),
    ("Quelles régions sont les moins peuplées ?", "pop_totale"),
]

DOIVENT_ECHOUER = [
    "Quel est le taux d'alphabétisation par région ?",
    "Quel est le prix du kilo de mangue à Kaolack ?",
    "Combien de touristes ont visité le Sénégal ?",
]

# Copie locale de la liste de mots vides, pour que ce script reste
# indépendant de recherche.py et mesure bien la même entrée.
VIDES = {
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "l",
    "quel", "quelle", "quels", "quelles", "est", "sont", "combien",
    "y", "a", "t", "il", "en", "au", "aux", "dans", "pour", "par",
    "sur", "avec", "que", "qui", "quoi", "ou", "et", "me", "moi",
    "donne", "montre", "affiche", "liste", "cherche", "trouve",
    "je", "veux", "voudrais", "peux", "tu", "vous", "s", "ce", "cette",
    "comment", "pourquoi", "quand", "plus", "moins", "evolue",
    "evolution", "regions", "region", "departement", "carte",
}


def sans_accents(s):
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def mots_utiles(question):
    s = sans_accents(question).lower()
    return [m for m in re.findall(r"[a-z0-9']+", s)
            if m not in VIDES and len(m) > 2]


# ---------------------------------------------------------------------

TABLE = Indicateur._meta.db_table

REQUETE = f"""
    SELECT code,
           similarity(txt, %s)      AS sim,
           word_similarity(%s, txt) AS wsim
    FROM (
        SELECT code,
               unaccent(lower(
                   libelle || ' ' || code || ' ' ||
                   array_to_string(synonymes, ' ')
               )) AS txt
        FROM {TABLE}
    ) fiches
    ORDER BY wsim DESC, sim DESC
    LIMIT 3
"""


def verifier_unaccent():
    with connection.cursor() as cur:
        try:
            cur.execute("SELECT unaccent('éàç')")
            cur.fetchone()
        except Exception:
            print("\n  unaccent absent. Installe-la puis relance :")
            print('    CREATE EXTENSION IF NOT EXISTS unaccent;\n')
            raise SystemExit(1)


def mesurer(question):
    """Meilleur score atteint par un mot de la question, deux méthodes."""
    mots = mots_utiles(question)
    best_sim = {"code": None, "score": 0.0, "mot": None}
    best_wsim = {"code": None, "score": 0.0, "mot": None}
    detail = []

    with connection.cursor() as cur:
        for mot in mots:
            cur.execute(REQUETE, [mot, mot])
            lignes = cur.fetchall()
            detail.append((mot, lignes))
            for code, sim, wsim in lignes:
                sim = float(sim or 0)
                wsim = float(wsim or 0)
                if sim > best_sim["score"]:
                    best_sim = {"code": code, "score": sim, "mot": mot}
                if wsim > best_wsim["score"]:
                    best_wsim = {"code": code, "score": wsim, "mot": mot}

    return mots, detail, best_sim, best_wsim


def main():
    verifier_unaccent()

    print()
    print("=" * 78)
    print("  APPARIEMENT MOT PAR MOT")
    print("=" * 78)

    resultats_ok = []
    for question, attendu in DOIVENT_TROUVER:
        mots, detail, bsim, bwsim = mesurer(question)
        juste_sim = bsim["code"] == attendu
        juste_wsim = bwsim["code"] == attendu

        print(f"\n  {question}")
        print(f"    attendu : {attendu}")
        print(f"    mots retenus : {mots or '— AUCUN —'}")
        for mot, lignes in detail:
            for code, sim, wsim in lignes:
                marque = "←" if code == attendu else " "
                print(f"      {mot:<14} {code:<22} "
                      f"sim {float(sim or 0):.3f}   "
                      f"wsim {float(wsim or 0):.3f}  {marque}")
        print(f"    similarity      → {bsim['code']} "
              f"({bsim['score']:.3f}) {'OK' if juste_sim else 'FAUX'}")
        print(f"    word_similarity → {bwsim['code']} "
              f"({bwsim['score']:.3f}) {'OK' if juste_wsim else 'FAUX'}")

        resultats_ok.append((question, attendu, bsim, bwsim,
                             juste_sim, juste_wsim))

    print()
    print("=" * 78)
    print("  QUESTIONS QUI DOIVENT ÊTRE REFUSÉES")
    print("=" * 78)

    resultats_ko = []
    for question in DOIVENT_ECHOUER:
        mots, _, bsim, bwsim = mesurer(question)
        print(f"\n  {question}")
        print(f"    mots retenus : {mots or '— AUCUN —'}")
        print(f"    similarity      → {bsim['code']} ({bsim['score']:.3f})")
        print(f"    word_similarity → {bwsim['code']} ({bwsim['score']:.3f})")
        resultats_ko.append((question, bsim, bwsim))

    # -----------------------------------------------------------------
    # Synthèse : un seuil n'est utile que s'il sépare les deux
    # populations. On cherche l'écart entre le PIRE score des questions
    # valides et le MEILLEUR score des questions à refuser.
    # -----------------------------------------------------------------

    print()
    print("=" * 78)
    print("  SÉPARATION")
    print("=" * 78)

    for nom, cle in (("similarity", 3), ("word_similarity", 4)):
        i = 2 if nom == "similarity" else 3
        pire_valide = min(r[i]["score"] for r in resultats_ok)
        # On ne compte comme valide que celles où la bonne réponse sort
        # première : un score haut sur le mauvais indicateur ne vaut rien.
        justes = [r for r in resultats_ok if r[4 if i == 2 else 5]]
        pire_juste = min((r[i]["score"] for r in justes), default=0.0)
        meilleur_bruit = max(r[i]["score"] for r in resultats_ko)

        print(f"\n  {nom}")
        print(f"    bonnes réponses en tête : "
              f"{len(justes)}/{len(resultats_ok)}")
        print(f"    plus faible score utile : {pire_juste:.3f}")
        print(f"    plus fort score de bruit : {meilleur_bruit:.3f}")
        marge = pire_juste - meilleur_bruit
        if marge > 0:
            seuil = meilleur_bruit + marge / 2
            print(f"    marge : {marge:.3f}  →  seuil conseillé "
                  f"{seuil:.2f}")
        else:
            print(f"    marge : {marge:.3f}  →  AUCUN SEUIL NE SÉPARE. "
                  f"Le bruit score aussi haut que le signal.")

    print()
    print("  Le seuil conseillé de word_similarity va dans recherche.py")
    print("  (SEUIL) et dans plan.py (SEUIL_REPLI). Prends la valeur")
    print("  basse des deux si elles diffèrent : mieux vaut un refus de")
    print("  trop qu'une réponse sur le mauvais indicateur.")
    print()


main()