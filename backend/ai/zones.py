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


def zones_citees(question, maximum=6):
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

# Forme courante d'une commune dont le nom officiel est plus long.
ALIAS_COMMUNES = {"TOUBA": "TOUBA MOSQUEE"}

# Mots à majuscule qui suivent souvent « de », « à »… sans être des lieux.
NON_LIEUX = {"SENEGAL", "RGPH", "ANSD", "PIB", "NORD", "SUD", "EST",
             "OUEST", "CENTRE", "AFRIQUE", "ETAT"}

# « population de Touba », « chômage à Ndiambour » : un mot à majuscule
# après une préposition de lieu.
RE_LIEU = re.compile(
    r"\b(?:à|a|au|aux|de|du|dans|sur)\s+"
    r"([A-ZÀ-Ý][\w'’-]{2,}(?:\s+[A-ZÀ-Ý][\w'’-]+)*)")


def _communes():
    """
    (clé normalisée, nom stocké) des communes au nom NON ambigu, noms
    longs d'abord. Un nom porté par plusieurs communes (Missirah,
    Dinguiraye…) n'est pas reconnu : on ne devine pas laquelle.
    """
    from collections import Counter
    from geography.models import Niveau, Zone

    noms = list(Zone.objects.filter(niveau=Niveau.COMMUNE)
                .values_list("nom", flat=True))
    compte = Counter(norm(n) for n in noms)
    vus, out = set(), []
    for nom in noms:
        cle = norm(nom)
        if compte[cle] == 1 and len(cle) >= 3 and cle not in vus:
            vus.add(cle)
            out.append((cle, nom))
    return sorted(out, key=lambda x: -len(x[0]))


def communes_citees(question, maximum=3):
    """Communes nommées dans la question, dans l'ordre d'apparition."""
    texte = f" {norm(question)} "
    for alias, cible in ALIAS_COMMUNES.items():
        if f" {alias} " in texte and f" {cible} " not in texte:
            texte = texte.replace(f" {alias} ", f" {cible} ")

    trouvees = []
    for cle, nom in _communes():
        if len(trouvees) >= maximum:
            break
        position = texte.find(f" {cle} ")
        if position == -1:
            continue
        trouvees.append((nom, position))
        texte = texte[:position] + " " + texte[position + len(cle) + 2:]
    trouvees.sort(key=lambda t: t[1])
    return [nom for nom, _ in trouvees]


def _vocabulaire_catalogue():
    """Mots des libellés et synonymes : « Natalité » n'est pas un lieu."""
    from catalog.models import Indicateur
    mots = set()
    for libelle, synonymes in Indicateur.objects.values_list(
            "libelle", "synonymes"):
        mots.update(norm(" ".join([libelle] + list(synonymes or []))).split())
    return mots


def lieu_inconnu(question):
    """Un lieu nommé avec une majuscule mais absent du référentiel, ou None."""
    vocabulaire = None
    for m in RE_LIEU.finditer(str(question or "")):
        mots = norm(m.group(1)).split()
        if any(w in NON_LIEUX for w in mots):
            continue
        if vocabulaire is None:
            vocabulaire = _vocabulaire_catalogue()
        if any(w in vocabulaire for w in mots):
            continue
        return m.group(1)
    return None


# « le quartier Castor », « le village de Ndiayène » : un lieu annoncé
# par son type est désigné, même hors de l'index des communes.
RE_QUARTIER_NOMME = re.compile(
    r"\b(?:quartier|village|hameau|localité|localite)s?\s+(?:de\s+|d['’]\s*)?"
    r"([A-ZÀ-Ý][\w'’-]*(?:\s+[A-ZÀ-Ý0-9][\w'’-]*)*)")


def corriger_zones(plan, question):
    """
    Remplace les zones du plan par celles réellement citées.
    Ordre : régions et départements, communes, quartier annoncé, lieu
    inconnu. Le pays entier seulement si AUCUN lieu n'est nommé.
    """
    citees = zones_citees(question)
    if citees in ([], ["SENEGAL"]):
        communes = communes_citees(question)
        if communes:
            citees = communes
        else:
            m = RE_QUARTIER_NOMME.search(str(question or ""))
            if m:
                plan["zones"] = [m.group(1).strip()]
                plan["niveau_zone"] = "quartier"
                return plan

    if citees:
        plan["zones"] = citees
        return plan

    inconnu = lieu_inconnu(question)
    if inconnu:
        plan["zones"] = [inconnu]
    elif plan.get("methode") in ("valeur_simple", "evolution", "repartition"):
        plan["zones"] = ["SENEGAL"]
    else:
        plan["zones"] = []
    return plan

RE_NIVEAU_DE = re.compile(
    r"\b(REGION|DEPARTEMENT|COMMUNE|QUARTIER|VILLAGE)S?\s+"
    r"(?:DE LA |DE L |DU |DE |D )")


def niveau_de_zone(question, nom):
    """
    Niveau que la QUESTION attache à une zone : « le département de
    Dakar » -> departement. None si elle n'en dit rien.

    Jamais celui du modèle, qui écrit « par commune » pour Dakar : il
    ferait prendre la commune de Kaolack pour la région de Kaolack.
    """
    texte, cible = norm(question), norm(nom)
    for m in RE_NIVEAU_DE.finditer(texte):
        if texte[m.end():].startswith(cible):
            n = m.group(1).lower()
            return "quartier" if n == "village" else n
    return None