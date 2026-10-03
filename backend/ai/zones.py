"""
backend/ai/zones.py

StatSense AI — Reconnaissance des zones citées dans une question

Les zones forment une liste fermée et connue : 1 pays, 14 régions,
46 départements. Les repérer dans une question est un travail
déterministe, qui n'a rien à gagner à passer par un modèle de langage.

Confier cette tâche au modèle pose au contraire un problème mesurable :
sur un modèle de petite taille, les zones citées dans les exemples du
prompt se recopient dans la réponse. Une question sur Kaolack ressort
avec « THIES » parce que c'est la zone de l'exemple.

Ce module est donc appliqué APRÈS l'extraction, et ce qu'il trouve fait
autorité sur ce que le modèle a proposé.
"""

import re
import unicodedata


def norm(s):
    """Majuscules, sans accents, ponctuation ramenée à des espaces."""
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


# Formulations courantes qui désignent le pays entier.
NATIONAL = {
    "SENEGAL", "AU SENEGAL", "DU SENEGAL", "NATIONAL", "AU NIVEAU NATIONAL",
    "DANS LE PAYS", "TOUT LE PAYS", "ENSEMBLE DU PAYS", "PAYS",
}

# Terminaisons des gentilés : un utilisateur écrit « les Thiessois » ou
# « la population dakaroise » aussi naturellement que le nom de la ville.
# Le S de « Thiessois » est une consonne de liaison, d'où les formes en
# S doublé.
GENTILES = (
    "OIS", "OISE", "OISES",
    "SOIS", "SOISE", "SOISES",
    "AIS", "AISE", "AISES",
    "IEN", "IENNE", "IENS", "IENNES",
    "AIN", "AINE", "AINS", "AINES",
    "ITE", "ITES",
)


def _index():
    """
    Zones candidates, noms longs en premier.

    Seuls le national, les régions et les départements sont reconnus :
    les communes et quartiers sont plus de vingt mille et leurs noms sont
    trop souvent homonymes pour un appariement par sous-chaîne.

    Le tri par longueur décroissante évite qu'un nom court capture un nom
    long : « SAINT LOUIS » doit être reconnu avant que « LOUIS » n'ait sa
    chance.
    """
    from geography.models import Niveau, Zone

    zones = Zone.objects.filter(
        niveau__in=[Niveau.NATIONAL, Niveau.REGION, Niveau.DEPARTEMENT]
    ).values_list("nom", "niveau")

    vus, out = set(), []
    for nom, niveau in zones:
        cle = norm(nom)
        if cle and cle not in vus:
            vus.add(cle)
            out.append((cle, nom, niveau))
    return sorted(out, key=lambda x: -len(x[0]))


def _position_gentile(texte, cle):
    """
    Cherche un gentilé formé sur le nom de zone : « dakarois » pour
    Dakar, « thiessois » pour Thiès.

    Ne s'applique qu'aux noms d'au moins quatre lettres et sans espace,
    pour éviter les rapprochements hasardeux sur les noms composés.
    """
    if len(cle) < 4 or " " in cle:
        return -1
    for mot in re.findall(r"[A-Z0-9]+", texte):
        if len(mot) > len(cle) and mot.startswith(cle):
            if mot[len(cle):] in GENTILES:
                return texte.find(f" {mot} ")
    return -1


def zones_citees(question, maximum=3):
    """
    Zones effectivement nommées dans la question, dans l'ordre où elles
    apparaissent.

    Une zone déjà reconnue est retirée du texte examiné, pour qu'un même
    fragment ne serve pas deux fois.
    """
    texte = f" {norm(question)} "

    trouvees = []
    if any(f" {m} " in texte for m in NATIONAL):
        trouvees.append(("SENEGAL", 0))

    for cle, nom, _niveau in _index():
        if len(trouvees) >= maximum:
            break
        if nom in [t[0] for t in trouvees]:
            continue

        motif = f" {cle} "
        position = texte.find(motif)
        longueur = len(motif)

        if position == -1:
            # Le nom exact est absent : un gentilé peut malgré tout
            # désigner la zone.
            position = _position_gentile(texte, cle)
            if position == -1:
                continue
            longueur = len(texte[position:].split(" ", 2)[1]) + 2

        trouvees.append((nom, position))
        texte = texte[:position] + " " + texte[position + longueur:]

    trouvees.sort(key=lambda t: t[1])
    return [nom for nom, _ in trouvees][:maximum]


def corriger_zones(plan, question):
    """
    Remplace les zones du plan par celles réellement citées.

    Quand la question n'en nomme aucune, le sens dépend de la méthode :
    une valeur, une évolution ou une répartition portent sur le pays
    entier — « quel est le taux de chômage actuel ? » n'est pas une
    question incomplète — tandis qu'un classement ou une carte portent
    sur toutes les zones d'un niveau, et n'ont donc pas besoin qu'on en
    nomme une.
    """
    citees = zones_citees(question)

    if citees:
        plan["zones"] = citees
    elif plan.get("methode") in ("valeur_simple", "evolution", "repartition"):
        plan["zones"] = ["SENEGAL"]
    else:
        plan["zones"] = []

    return plan