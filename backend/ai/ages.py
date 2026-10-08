"""
backend/ai/ages.py

StatSense AI — Groupes d'âge cités dans une question

Garde-fou, pas encore une fonctionnalité.

Constaté : « Y a-t-il plus d'hommes adultes que de femmes au Sénégal ? »
-> rapport_masculinite = 102,59, le mot « adultes » ignoré. Or chez les
20 ans et plus, le rapport vaut 96,0 : la réponse affichée disait
l'inverse de la réalité.

Le moteur ne filtre que sur UNE modalité. Un groupe d'âge est une somme
de tranches qu'il ne sait pas encore servir : on refuse explicitement,
plutôt que de répondre pour toute la population.

Deux cas passent :
  - le plan porte déjà une tranche d'âge : elle est nommée en note, pour
    que l'utilisateur voie ce qui a été retenu ;
  - une répartition par âge : elle affiche toutes les tranches.
"""

import re
import unicodedata

GROUPES = (
    "adulte", "adultes", "enfant", "enfants", "jeune", "jeunes",
    "jeunesse", "adolescent", "adolescents", "adolescente",
    "adolescentes", "bebe", "bebes", "nourrisson", "nourrissons",
    "majeur", "majeurs", "majeure", "majeures", "mineur", "mineurs",
    "mineure", "mineures", "senior", "seniors", "personnes agees",
    "personne agee", "troisieme age", "vieillards", "retraites",
)


RE_AGES = re.compile(
    r"\b(?:(?:moins|plus) de \d{1,3} ans"
    r"|\d{1,3} ans (?:et|ou) (?:plus|moins)"
    r"|de \d{1,3} a \d{1,3} ans"
    r"|\d{1,3} \d{1,3} ans)\b"
)

# « depuis plus de 10 ans », « il y a moins de 5 ans » : une durée,
# pas un âge.
RE_DUREE = re.compile(r"\b(?:depuis|il y a|en|dans|ces|pendant)\s+$")


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def age_cite(question):
    """Le groupe d'âge nommé dans la question, ou None.

    Les âges chiffrés d'abord : « personnes âgées de moins de 15 ans »
    désigne les moins de 15 ans, pas les personnes âgées.
    """
    texte = f" {_norm(question)} "
    for m in RE_AGES.finditer(texte):
        if not RE_DUREE.search(texte[:m.start()]):
            return m.group(0)
    for g in GROUPES:
        if f" {g} " in texte:
            return g
    return None


def age_servi(plan):
    """Le plan porte-t-il une tranche d'âge, ou une répartition par âge ?"""
    if (plan.get("filtres") or {}).get("age"):
        return True
    return (plan.get("methode") == "repartition"
            and plan.get("dimension") == "age")


def tranches_citees(question):
    """
    Tranches de 5 ans publiées dont la somme donne EXACTEMENT le groupe
    cité, et une précision d'interprétation éventuelle. (None, None) sinon.

        « moins de 15 ans »   -> Y0T4, Y5T9, Y10T14
        « 60 ans ou plus »    -> Y60T64 … Y75T79, Y_GE80
        « de 15 à 34 ans »    -> Y15T19 … Y30T34

    Une borne qui ne tombe pas sur une limite de tranche (« moins de 18
    ans ») ne peut pas être servie exactement : refus.
    """
    texte = f" {_norm(question)} "
    m = next((x for x in RE_AGES.finditer(texte)
              if not RE_DUREE.search(texte[:x.start()])), None)
    if m is None:
        return None, None
    g = m.group(0)
    n = [int(v) for v in re.findall(r"\d{1,3}", g)]
    precision = None
    if g.startswith("moins de"):
        bas, haut = 0, n[0] - 1
    elif g.startswith("plus de"):
        bas, haut = n[0], None
        precision = f"« plus de {n[0]} ans » est lu comme « {n[0]} ans et plus »."
    elif g.endswith("plus"):
        bas, haut = n[0], None
    elif len(n) == 2 and not g.endswith("moins"):
        bas, haut = n[0], n[1]
    else:
        return None, None
    if bas % 5 or (haut is not None and ((haut + 1) % 5 or haut >= 80)):
        return None, None
    codes = [f"Y{a}T{a + 4}"
             for a in range(bas, 80 if haut is None else haut + 1, 5)]
    if haut is None:
        codes.append("Y_GE80")
    return (codes or None), precision