"""
backend/ai/cadrage.py

StatSense AI — Méthode, sens du classement, nombre d'éléments

Cinquième extraction, après les zones, les ventilations et les périodes,
et pour la même raison : ce qui a une forme fermée revient au code.

Quatre éléments sont traités ici.


1. LA MÉTHODE

Dernier champ à forme fermée qui restait au modèle — cinq valeurs — et
dernière cause d'échec dur mesurée :

    « Quelles régions sont les moins peuplées ? »
        -> methode: null, deux fois de suite
        -> Plan inexploitable après deux essais

Le modèle omettait simplement le champ. `valider()` rejetait, le second
essai échouait pareil, et la question tombait au repli déterministe —
alors que l'information était dans la question depuis le début : « les
moins peuplées » annonce un classement, et `ordre_cite` ci-dessous le
détectait déjà sans que personne n'en tire parti.

Le vocabulaire existait d'ailleurs, dans `plan.py`, mais il ne servait
qu'au repli : utilisé seulement quand le modèle est en panne, jamais
quand il se trompe. Il est ici désormais, et `plan.py` l'emprunte.

L'ordre des familles compte, du plus spécifique au plus général :
« Comment l'accès à l'eau a-t-il évolué ? » contient « a-t-il » et
« évolué » — c'est l'évolution qui décide, pas le reste.

Le modèle garde la main quand il propose une méthode valide : lui seul lit
l'intention derrière « montre-moi ça sur une carte ». Le code ne comble
qu'un vide.


2. LE SENS DU CLASSEMENT

Mesuré sur les plans réellement produits :

    « Où les ménages sont-ils les plus grands ? »  -> ordre: asc
    « Quelles régions sont les moins peuplées ? »  -> ordre: asc

Le premier est faux : « les plus grands » demande un tri décroissant. Le
classement affiché était l'inverse exact de la question posée — le pire
type d'erreur, puisque la réponse est plausible et complète.

Le plus instructif est que « Où les ménages sont-ils les plus grands ? »
figure MOT POUR MOT dans les exemples du prompt, avec `ordre: desc`. Le
modèle ne l'a pas recopié. Sur un modèle de trois milliards de
paramètres, un exemple n'est pas une garantie ; « les plus » contre
« les moins » est en revanche une opposition de deux mots.


3. LE NOMBRE D'ÉLÉMENTS

    « Quelles sont les 5 régions les plus peuplées ? »  -> top_n: 5   (juste)
    « Quelles régions sont les moins peuplées ? »       -> top_n: 1   (faux)
    « Où les ménages sont-ils les plus grands ? »       -> top_n: 1   (faux)

Quand un nombre figure dans la question, le modèle le reprend. Quand il
n'y en a pas, il produit 1 — et le classement ne rend qu'une ligne. Comme
`valider()` ne remplace que les valeurs absentes ou nulles, un `1` passe
la validation.

Un nombre dans une question est un nombre. Les années sont exclues par
construction : la recherche ne porte que sur un ou deux chiffres, et
`\\b` empêche de capturer « 20 » dans « 2016 ».


4. LA COHÉRENCE DE LA MÉTHODE

    « Quel est le taux de natalité par région ? »  -> repartition

Une répartition décompose un total selon une ventilation — âge, secteur,
quintile. « par région » n'est pas une ventilation, c'est un découpage
géographique : la demande est un classement, ou une carte.

Deux tests, parce que le premier seul ne suffisait pas. Une répartition
sans dimension n'a plus d'objet — c'est le cas quand filtres.py a vidé
une dimension géographique inventée. Mais le modèle peut aussi produire
une dimension recevable tout en se trompant de méthode : « taux de
natalité par région » restait alors une répartition, et le moteur la
refusait à juste titre puisqu'un pour-mille ne se décompose pas.

D'où le second test, sur la question elle-même : « par région », « par
département », « par commune » écartent la répartition, quelle que soit
la dimension proposée. Ces formulations forment une liste fermée, comme
tout le reste de ce module.
"""

import re
import unicodedata

TOP_N_DEFAUT = 10

# Méthodes du moteur. Déclarées ici parce que c'est ici qu'on les déduit ;
# plan.py les importe de ce module pour valider ce que le modèle propose.
METHODES = {"valeur_simple", "classement", "evolution", "geographique",
            "repartition"}

# Ce que la question dit de la méthode. Du plus spécifique au plus
# général : la première famille qui matche décide.
#
# « part de » ne figure PAS dans la famille `repartition`, et c'est
# volontaire : « quelle est la part de Dakar dans la population » demande
# une valeur unique — celle de l'indicateur `part_population` — et non la
# décomposition d'un total.
MOTS_METHODE = [
    (("sur une carte", "sur la carte", "carte", "cartograph", "choroplet",
      "localise", "geolocalise"),
     "geographique"),

    (("repartition", "repartir", "ventilation", "ventile", "decomposition",
      "pyramide", "structure par", "par tranche", "par tranches",
      "par secteur", "par secteurs", "par categorie", "par categories",
      "par quintile", "par quintiles", "par age", "par sexe"),
     "repartition"),

    (("evolu", "progress", "tendance", "depuis", "au fil", "croissance",
      "augment", "diminu", "varia", "entre 19", "entre 20", "trajectoire",
      "historique"),
     "evolution"),

    (("les plus", "les moins", "plus grand", "plus grande", "plus eleve",
      "plus elevee", "plus faible", "plus fort", "plus forte", "plus bas",
      "plus basse", "plus peuple", "plus peuplee", "classement", "classe",
      "top", "meilleur", "meilleure", "pire", "palmares",
      "quelles regions", "quels departements", "quelles communes",
      "quelle region a", "quelle region est", "quel departement a",
      "ou trouve", "ou sont", "ou se trouvent", "ou les"),
     "classement"),
]

# Les formes décroissantes sont testées EN SECOND : « les plus petites »
# contient « les plus », mais c'est « plus petit » qui décide.
MOTS_ASC = (
    "moins", "plus petit", "plus petits", "plus petite", "plus petites",
    "plus faible", "plus faibles", "plus bas", "plus basse", "plus basses",
    "moindre", "moindres", "dernier", "derniers", "derniere", "dernieres",
    "minimum", "mini", "pire", "pires", "queue de classement",
)

MOTS_DESC = (
    "plus grand", "plus grands", "plus grande", "plus grandes",
    "plus eleve", "plus elevee", "plus elevees", "plus eleves",
    "plus fort", "plus forts", "plus forte", "plus fortes",
    "plus haut", "plus hauts", "plus haute", "plus hautes",
    "plus peuple", "plus peuplee", "plus peuplees", "plus peuples",
    "les plus", "top", "meilleur", "meilleurs", "meilleure", "meilleures",
    "premier", "premiers", "premiere", "premieres",
    "maximum", "maxi", "palmares", "tete de classement",
)


# Découpages géographiques exprimés dans la question. Ils désignent un
# niveau, jamais une ventilation.
PAR_GEOGRAPHIQUE = (
    "par region", "par regions", "par departement", "par departements",
    "par commune", "par communes", "par quartier", "par quartiers",
    "par zone", "par zones", "par ville", "par villes",
    "par localite", "par localites",
)


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def methode_citee(question):
    """
    Méthode annoncée par la question, ou None si rien ne la désigne.

    Un découpage géographique n'ouvre pas droit à `repartition` : « par
    région » désigne une maille, pas une ventilation. Il désigne en
    revanche un classement, et c'est le dernier test de cette fonction :

        « Quel est le taux de natalité par région ? »

    n'emploie aucun mot de classement — ni superlatif, ni « quelles
    régions » — et demande pourtant bien les quatorze valeurs. Sans ce
    test elle deviendrait une valeur simple, donc un refus pour zone
    manquante.
    """
    texte = f" {_norm(question)} "
    for motifs, methode in MOTS_METHODE:
        if not any(f" {m}" in texte for m in motifs):
            continue
        if methode == "repartition" and decoupage_geographique(question):
            continue
        return methode

    if decoupage_geographique(question):
        return "classement"
    return None


def ordre_cite(question):
    """
    Sens du tri demandé : « desc », « asc », ou None si la question ne le
    dit pas.

    Les formes croissantes sont cherchées d'abord, parce qu'elles sont les
    plus spécifiques : « les plus petites régions » contient « les plus »,
    et ce n'est pas un tri décroissant.
    """
    texte = f" {_norm(question)} "

    for m in MOTS_ASC:
        if f" {m}" in texte:
            return "asc"
    for m in MOTS_DESC:
        if f" {m}" in texte:
            return "desc"
    return None


def nombre_cite(question):
    """
    Nombre d'éléments demandé, ou None.

    Un ou deux chiffres seulement : les années comportent quatre chiffres
    et `\\b` interdit de capturer une partie d'un nombre plus long.
    Au-delà de 60, le moteur plafonne de toute façon.
    """
    for m in re.finditer(r"\b(\d{1,2})\b", _norm(question)):
        n = int(m.group(1))
        if 2 <= n <= 60:
            return n
    return None


def decoupage_geographique(question):
    """La question demande-t-elle un découpage par zone plutôt qu'une
    ventilation ?"""
    texte = f" {_norm(question)} "
    return any(f" {m}" in texte for m in PAR_GEOGRAPHIQUE)


def corriger_cadrage(plan, question):
    """
    Aligne la méthode, le sens du tri, le nombre d'éléments et la
    cohérence du plan sur ce que la question dit réellement.

    Appelé après corriger_zones, corriger_filtres et corriger_periode :
    la cohérence de méthode dépend de `dimension`, que filtres.py a pu
    vider.
    """
    # --- méthode ---
    # `valider()` laisse le champ à None quand le modèle l'omet ou propose
    # une valeur inconnue : c'est ici qu'il est rempli. Une méthode valide
    # proposée par le modèle est conservée — lui seul lit l'intention
    # derrière « montre-moi ça sur une carte ».
    if plan.get("methode") not in METHODES:
        plan["methode"] = methode_citee(question) or "valeur_simple"

        # Compléments que `valider()` appliquait quand il connaissait la
        # méthode. Ils suivent la méthode, donc ils viennent ici.
        if plan["methode"] == "geographique":
            plan["niveau"] = plan.get("niveau") or "region"
        elif plan["methode"] == "repartition":
            plan["niveau"] = plan.get("niveau") or "national"

    # --- sens du tri ---
    sens = ordre_cite(question)
    if sens:
        plan["ordre"] = sens

    # --- cohérence de la méthode ---
    # Une répartition suppose une ventilation. Sans dimension elle n'a
    # plus d'objet ; avec un découpage géographique dans la question, ce
    # n'en était pas une.
    if plan.get("methode") == "repartition" and (
            not plan.get("dimension") or decoupage_geographique(question)):
        plan["methode"] = "classement"
        plan["dimension"] = None
        plan["niveau"] = plan.get("niveau") or "region"
        if plan["niveau"] == "national":
            # Un classement national ne classerait qu'une zone.
            plan["niveau"] = "region"

    # --- nombre d'éléments ---
    if plan.get("methode") == "classement":
        plan["niveau"] = plan.get("niveau") or "region"
        n = nombre_cite(question)
        if n is not None:
            plan["top_n"] = n
        elif not plan.get("top_n") or int(plan["top_n"]) < 2:
            # Le modèle produit « 1 » en l'absence de nombre dans la
            # question, et valider() ne corrige que les valeurs nulles.
            plan["top_n"] = TOP_N_DEFAUT

    return plan