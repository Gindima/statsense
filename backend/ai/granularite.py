"""
backend/ai/granularite.py

StatSense AI — Alignement du niveau demandé sur le niveau publié

Sixième correction déterministe, et la même logique que les cinq autres :
le niveau géographique forme une liste fermée de cinq valeurs, et la
granularité de chaque indicateur est déclarée au catalogue. Le rapport
entre les deux se calcule, il ne s'interprète pas.


CE QU'ELLE RÉPARE

Deux questions sur quinze échouaient ainsi :

    « Quel est le taux de chômage à Dakar ? »
        taux_chomage_a · par departement · DAKAR
        -> granularite_indisponible

    « Comment le chômage à Dakar a-t-il évolué depuis 2015 ? »
        taux_chomage_a · par departement · DAKAR
        -> granularite_indisponible

Le chômage est publié à la région. Le modèle avait écrit
`niveau: departement`, ce qui n'est pas absurde — Dakar EST un
département — mais la région Dakar existe aussi, et c'est elle que porte
la série. Le refus était donc exact sur la lettre du plan et faux sur
l'intention de la question.


POURQUOI CE N'EST PAS AU MODÈLE DE LE FAIRE

Il faudrait qu'il retienne, pour chacun des seize indicateurs, le niveau
auquel il est publié, et qu'il sache lequel des noms de zones existe à ce
niveau. Les fiches portent bien `niveau_min`, mais c'est une contrainte à
respecter, pas une information à recopier : la respecter demande une
comparaison, et une comparaison se fait en deux lignes de code.


LA RÈGLE, ET SA LIMITE

Le moteur sait agréger, il ne sait pas désagréger — même principe que le
départage du catalogue. Si le niveau demandé est plus fin que le niveau
publié :

    toutes les zones du plan existent au niveau publié
        -> on remonte au niveau publié, la question a une réponse

    au moins une n'y existe pas
        -> on ne touche à rien, et le moteur refuse

La seconde branche est celle de « Quel est le taux de chômage à Mbour ? ».
Mbour est un département sans région homonyme : aucune agrégation ne peut
produire un taux de chômage pour Mbour, et le refus est la bonne réponse.
C'est elle qui garantit que cette correction n'invente rien.

Exigence de l'unanimité : si le plan porte DAKAR et MBOUR, remonter à la
région répondrait pour l'une et pas pour l'autre. Mieux vaut un refus
lisible qu'une réponse partielle sans mention de ce qui manque.

Un plan sans zone est remonté sans condition : c'est le cas des
classements, où le niveau désigne la maille du classement et non une zone
à retrouver.
"""

import re
import unicodedata

from ai.recherche import FINESSE


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def _noms_au_niveau(niveau):
    """Noms normalisés des zones existant à ce niveau, ou None si la
    géographie est inaccessible."""
    try:
        from geography.models import Zone
        return {
            _norm(n) for n in
            Zone.objects.filter(niveau=niveau).values_list("nom", flat=True)
        }
    except Exception:
        return None


def _granularite_publiee(code):
    """Niveau le plus fin auquel l'indicateur est publié, ou None."""
    if not code:
        return None
    try:
        from catalog.models import Indicateur
        i = (Indicateur.objects.filter(code=code)
             .only("granularite_geo_min").first())
    except Exception:
        return None
    return i.granularite_geo_min if i else None


def corriger_granularite(plan):
    """
    Remonte `niveau` au niveau de publication de l'indicateur quand le
    plan demande plus fin que ce qui existe et que les zones le
    permettent.

    Appelée en dernier, après corriger_cadrage : celui-ci peut écrire
    `niveau` lui-même en requalifiant une répartition en classement.

    Ne refuse jamais et ne lève jamais : laisser le plan intact rend la
    main au moteur, qui refuse avec un motif et une source.
    """
    publie = _granularite_publiee(plan.get("indicateur"))
    demande = plan.get("niveau")

    if publie not in FINESSE or demande not in FINESSE:
        return plan
    if FINESSE[demande] <= FINESSE[publie]:
        return plan                      # déjà au niveau publié, ou plus large

    zones = [z for z in (plan.get("zones") or []) if z]
    if not zones:
        plan["niveau"] = publie          # classement : pas de zone à retrouver
        return plan

    disponibles = _noms_au_niveau(publie)
    if disponibles is None:
        return plan
    if all(_norm(z) in disponibles for z in zones):
        plan["niveau"] = publie

    return plan