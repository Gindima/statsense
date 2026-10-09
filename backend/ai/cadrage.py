"""
backend/ai/cadrage.py

StatSense AI — Méthode, sens du classement, nombre d'éléments

Cinquième extraction, après les zones, les ventilations et les périodes,
et pour la même raison : ce qui a une forme fermée revient au code.

Cinq éléments sont traités ici.


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


5. LA QUESTION AU SINGULIER

    « Quelle région a la taille moyenne des ménages la plus élevée ? »
        -> dix lignes

Dix lignes à une question qui en demande une. Le singulier et le pluriel
s'opposent sur une lettre — « quelle région » contre « quelles régions » —
et cette lettre dit combien de réponses sont attendues. C'est une forme
fermée, donc elle revient ici.

CINQ, ET NON UNE.

Rendre une seule ligne répondrait à la lettre et tromperait sur le fond.
Sur cette question précise, les deux premières valeurs sont SÉDHIOU à
12,10 et MATAM à 11,56 personnes par ménage : 4,5 % d'écart. Un leader
qui n'est pas détaché. N'afficher que la tête transforme un classement
serré en évidence, et c'est le lecteur qui paie l'approximation.

Cinq lignes répondent — la première EST la réponse — et laissent voir si
la tête se distingue. Dix noient la réponse dans son contexte, une la
coupe de son contexte.

CETTE CORRECTION PRIME SUR LE MODÈLE.

Comme `ordre_cite`, et pour la même raison : la forme de la question fait
autorité. L'ancienne version ne corrigeait `top_n` que si le modèle avait
proposé une valeur inférieure à 2 ; un `10` proposé sur une question au
singulier passait donc intact. L'ordre de priorité est désormais explicite
— nombre cité dans la question, puis forme singulière, puis proposition du
modèle, puis défaut.
"""

import re
import unicodedata

TOP_N_DEFAUT = 10

# Nombre d'éléments rendus à une question formulée au singulier. Voir la
# section 5 de l'en-tête pour le choix de cinq plutôt qu'un.
TOP_N_SINGULIER = 5

# Méthodes du moteur. Déclarées ici parce que c'est ici qu'on les déduit ;
# plan.py les importe de ce module pour valider ce que le modèle propose.

METHODES = {"valeur_simple", "classement", "evolution", "geographique",
            "repartition", "comparaison"}

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
      "augment", "diminu", "hausse", "baisse", "varia", "entre 19", "entre 20", "trajectoire",
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


# Noms de zone au singulier. Au pluriel ils ne disent plus rien du nombre
# de réponses attendues, et c'est précisément l'information cherchée.
NOMS_ZONE_SINGULIER = (
    "region", "departement", "commune", "arrondissement",
    "quartier", "village", "ville", "zone", "localite",
)

_NOMS = "|".join(NOMS_ZONE_SINGULIER)

# « quelle région », « quel département », « quelle est la commune ».
#
# `que(?:l|lle)\b` ne matche ni « quels » ni « quelles » : après « quel »
# vient un « l », après « quelle » un « s », et dans les deux cas il n'y a
# pas de frontière de mot. L'opposition singulier/pluriel tient donc à la
# limite `\b`, sans liste d'exceptions.
RE_INTERROGATIF_SINGULIER = re.compile(
    rf"\bque(?:l|lle)\b(?:\s+est\s+(?:le|la))?\s+(?:{_NOMS})\b"
)

# « la région la plus peuplée », sans interrogatif. Même demande, autre
# tournure.
RE_SUPERLATIF_DEFINI = re.compile(
    rf"\b(?:le|la)\s+(?:{_NOMS})\s+(?:le|la)\s+(?:plus|moins)\b"
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


# « du plus élevé au plus faible » : le premier terme donne le sens.
RE_DU_AU = re.compile(r"\bdu (.+?) au ")


def _sens(texte):
    for m in MOTS_ASC + ("croissant",):
        if f" {m}" in texte:
            return "asc"
    for m in MOTS_DESC + ("le plus", "la plus", "decroissant"):
        if f" {m}" in texte:
            return "desc"
    return None


def ordre_cite(question):
    """Sens du tri demandé : « desc », « asc », ou None."""
    texte = f" {_norm(question)} "
    m = RE_DU_AU.search(texte)
    if m:
        sens = _sens(f" {m.group(1)} ")
        if sens:
            return sens
    return _sens(texte)


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


def interrogatif_singulier(question):
    """
    La question demande-t-elle UNE zone, et non plusieurs ?

    « Quelle région a la taille moyenne la plus élevée ? » attend une
    réponse ; « Quelles régions sont les moins peuplées ? » en attend
    plusieurs. Le nombre voulu est dans la question, à une lettre près.

    Vrai n'entraîne pas une seule ligne mais cinq : voir la section 5 de
    l'en-tête.
    """
    texte = _norm(question)
    return bool(RE_INTERROGATIF_SINGULIER.search(texte)
                or RE_SUPERLATIF_DEFINI.search(texte))


def decoupage_geographique(question):
    """La question demande-t-elle un découpage par zone plutôt qu'une
    ventilation ?"""
    texte = f" {_norm(question)} "
    return any(f" {m}" in texte for m in PAR_GEOGRAPHIQUE)

# « Quelle région compte le moins d'habitants ? » : un nom de zone
# interrogé, avec un superlatif, demande un classement.
RE_QUEL_ZONE = re.compile(
    rf"\bque(?:l|lle)s?\b(?:\s+est\s+(?:le|la))?\s+({_NOMS})s?\b")

# « les départements de la région de Dakar » : une liste de zones.
RE_ZONES_LISTEES = re.compile(
    r"\b(?:les|des|aux|chaque)\s+(region|departement|commune|quartier)s?"
    r"\s+(?:de|du|d)\b")

NIVEAU_DU_NOM = {"village": "quartier", "ville": "commune",
                 "localite": "quartier", "arrondissement": "departement",
                 "zone": "region"}


# « le département le plus peuplé », « que les autres régions »
RE_SUPERLATIF_NIVEAU = re.compile(
    rf"\b(?:le|la)\s+({_NOMS})\s+(?:le|la)\s+(?:plus|moins)\b")
RE_AUTRES_ZONES = re.compile(
    r"\bautres\s+(region|departement|commune|quartier)s?\b")


def classement_demande(question):
    """Niveau du classement que la question demande, ou None."""
    texte = _norm(question)
    m = RE_QUEL_ZONE.search(texte)
    if m and ordre_cite(question):
        return NIVEAU_DU_NOM.get(m.group(1), m.group(1))
    for rx in (RE_SUPERLATIF_NIVEAU, RE_AUTRES_ZONES, RE_ZONES_LISTEES):
        m = rx.search(texte)
        if m:
            return NIVEAU_DU_NOM.get(m.group(1), m.group(1))
    return None

def deux_sexes(question):
    """La question nomme-t-elle les hommes ET les femmes ?"""
    from .filtres import MOTS
    texte = f" {_norm(question)} "
    vus = {v for motifs, (cle, v) in MOTS
           if cle == "sexe" and any(f" {m} " in texte for m in motifs)}
    return {"F", "M"} <= vus


def deux_milieux(question):
    """La question nomme-t-elle l'urbain ET le rural ?"""
    texte = f" {_norm(question)} "
    urbain = any(f" {m} " in texte for m in
                 ("urbain", "urbaine", "urbains", "urbaines"))
    rural = any(f" {m} " in texte for m in
                ("rural", "rurale", "ruraux", "rurales"))
    return urbain and rural


def corriger_comparaison(plan, question):
    """
    Plusieurs zones, les deux sexes ou les deux milieux : la question
    compare.

    Constaté : « Compare la population de Dakar et de Thiès » rendait le
    classement des communes de Dakar ; « différence entre urbain et
    rural » une répartition, refusée parce qu'un taux ne se répartit pas.
    """
    if plan.get("methode") not in ("valeur_simple", "classement",
                                   "repartition", "comparaison"):
        return plan

    axe = None
    if plan.get("indicateur") and (deux_sexes(question)
                                   or deux_milieux(question)):
        from catalog.models import Indicateur
        dims = (Indicateur.objects.filter(code=plan["indicateur"])
                .values_list("dimensions", flat=True).first()) or []
        if deux_sexes(question) and "sexe" in dims:
            axe = "sexe"
        elif deux_milieux(question) and "milieu" in dims:
            axe = "milieu"

    if len(plan.get("zones") or []) < 2 and not axe:
        return plan

    plan["methode"] = "comparaison"
    plan["dimension"] = axe
    plan["top_n"] = None
    plan["niveau"] = plan.get("niveau_zone")
    if axe:
        plan["filtres"] = {k: v for k, v in (plan.get("filtres") or {}).items()
                           if k != axe}
    return plan


RE_QUELLE_ANNEE = re.compile(r"\bquelles? annees?\b|\bannees? ou\b")
RE_DUREE = re.compile(r"\b(annees|serie|courbe|historique|periode)\b")

# « chaque quartier », « quels départements » : la maille demandée.
RE_MAILLE = re.compile(
    r"\b(?:chaque|par|les|des|aux|tous les|toutes les|quels?|quelles?)\s+"
    r"(region|departement|commune|quartier|village|localite)s?\b")

# « supérieure à 8 », « plus de 1 000 » — mais pas « plus de 60 ans ».
RE_SEUIL = re.compile(
    r"\b(?:superieure?s? a|inferieure?s? a|au dessus de|en dessous de|"
    r"au dela de|depassant|plus de|moins de)\s+(\d+(?: \d{3})*)")


def _intervalle(plan):
    p = plan.get("periode") or {}
    d, f = p.get("debut"), p.get("fin")
    return bool(d and f and str(d) != str(f))


def maille_demandee(question):
    m = RE_MAILLE.search(_norm(question))
    return NIVEAU_DU_NOM.get(m.group(1), m.group(1)) if m else None


def seuil_cite(question):
    texte = _norm(question)
    for m in RE_SEUIL.finditer(texte):
        if re.match(r"\s*ans\b", texte[m.end():]):
            continue
        return m.group(1)
    return None


def classement_evolution(question):
    """« Quelle région a connu la plus forte hausse ? » : un classement
    de variations, que le moteur ne sait pas faire."""
    texte = _norm(question)
    if methode_citee(question) != "evolution":
        return False
    if not re.search(r"\b(le|la|les) (plus|moins)\b", texte):
        return False
    return bool(classement_demande(question)
                or re.match(r"(ou|dans quelle|quelle|quel)\b", texte))

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

    # Une valeur simple qui demandait en fait un classement. Mesuré :
    # « Quelle région compte le moins d'habitants ? » -> SENEGAL 18 126 342.
    niveau_classe = classement_demande(question)

    # « Quelle année… ? » demande un point d'une série. Une « évolution »
    # sans mot d'évolution ni intervalle était une valeur ou un classement.
    texte_q = _norm(question)
    annee = bool(RE_QUELLE_ANNEE.search(texte_q))
    cite = methode_citee(question)
    if annee and plan.get("methode") in ("classement", "valeur_simple"):
        plan["methode"], plan["top_n"] = "evolution", None
    elif (plan.get("methode") == "evolution" and not annee
          and cite != "evolution" and not _intervalle(plan)
          and not RE_DUREE.search(texte_q)):
        if niveau_classe or cite == "classement":
            plan["methode"] = "classement"
            plan["niveau"] = niveau_classe or plan.get("niveau") or "region"
        else:
            plan["methode"] = "valeur_simple"

    if niveau_classe and (plan.get("methode") == "valeur_simple"
                          or (plan.get("methode") == "comparaison"
                              and len(plan.get("zones") or []) < 2)):
        plan["methode"] = "classement"
        plan["niveau"] = niveau_classe


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

    # Un classement portant sur UNE zone nommée, sans superlatif ni liste,
    # était une valeur. Constaté : « Quelle part de la population nationale
    # vit dans la région de Dakar ? » rendait les 14 régions.
    nommees = [z for z in plan.get("zones") or [] if z != "SENEGAL"]
    if (plan.get("methode") == "classement" and len(nommees) == 1
            and not niveau_classe and not ordre_cite(question)
            and not decoupage_geographique(question)
            and nombre_cite(question) is None):
        plan["methode"] = "valeur_simple"

    # --- nombre d'éléments ---
    #
    # Priorité décroissante, et chaque niveau dit pourquoi il passe avant
    # le suivant :
    #
    #   1. un nombre cité       la question le dit en chiffres
    #   2. la forme singulière  la question le dit en grammaire
    #   3. le plan du modèle    il a pu lire « une poignée de régions »
    #   4. le défaut            personne n'a rien dit
    #
    # Les deux premiers priment sur le modèle : ce sont des formes fermées,
    # et c'est tout l'objet de ce module.
    if plan.get("methode") == "classement":
        plan["niveau"] = plan.get("niveau") or "region"
        n = nombre_cite(question)
        if n is not None:
            plan["top_n"] = n
        elif interrogatif_singulier(question):
            plan["top_n"] = TOP_N_SINGULIER
            plan["reponse_unique"] = True
        elif not plan.get("top_n") or int(plan["top_n"]) < 2:
            # Le modèle produit « 1 » en l'absence de nombre dans la
            # question, et valider() ne corrige que les valeurs nulles.
            plan["top_n"] = TOP_N_DEFAUT

    return plan