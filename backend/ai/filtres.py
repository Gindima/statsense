"""
backend/ai/filtres.py

StatSense AI — Reconnaissance des ventilations citées dans une question

Même raisonnement que pour les zones : les modalités de sexe et de
milieu de résidence forment une liste fermée de quatre valeurs. Les
repérer dans une question ne demande pas un modèle de langage, et le
modèle s'en acquitte mal — il choisit l'indicateur mais oublie le
filtre, si bien qu'une demande impossible passe pour une demande
ordinaire.

L'enjeu n'est pas seulement de bien filtrer. C'est de permettre au
moteur de REFUSER : « combien de ménages dirigés par une femme » doit
produire un refus, puisque le nombre de ménages n'est pas ventilé par
sexe. Sans le filtre dans le plan, la validation n'a rien à examiner et
le système répond comme si de rien n'était.

Seules les dimensions détectables sans ambiguïté sont traitées ici. Les
tranches d'âge, quintiles, secteurs et catégories professionnelles
restent au modèle : leurs formulations sont trop variées pour une table
de mots-clés, et une détection approximative ferait plus de dégâts que
l'oubli qu'elle corrige.


UN NIVEAU GÉOGRAPHIQUE N'EST PAS UNE VENTILATION

Constaté sur « Évolution de la population de Dakar » : le modèle avait
placé `region` dans les filtres, recopié du libellé de l'indicateur
« Population par région et département ». Le moteur a refusé, à juste
titre puisque `region` ne figure pas dans les dimensions déclarées, mais
la question était légitime et la réponse existait.

La géographie est portée par `niveau` et `zones`, jamais par `filtres`
ni par `dimension`. Liste fermée de cinq valeurs, donc du ressort du
code : ces clés sont retirées sans condition. Même traitement pour le
temps, porté par `periode` : `dimension: annee` sur une évolution
désigne son axe, pas une ventilation.


NOMMER UN INDICATEUR N'EST PAS DEMANDER UNE VENTILATION

Constaté sur « Rapport de masculinité » :

    valeur · rapport_masculinite · par commune · DAKAR
    -> La ventilation ['sexe'] n'existe pas pour « Rapport de masculinité »

Refus injustifié. Le rapport de masculinité EST un rapport entre les
sexes ; les mots « hommes » et « femmes » de la question désignent
l'indicateur, ils ne réclament pas une ventilation par sexe. Cet
indicateur ne déclare d'ailleurs aucune dimension, et c'est normal :
le sexe est dans sa définition, pas dans ses axes de découpage.

Mais on ne peut pas se contenter de retirer les filtres non déclarés :
« combien de ménages dirigés par une femme » doit continuer de produire
un refus, puisque cette ventilation-là est réellement demandée et
réellement absente.

La distinction est décidable, et sans modèle : les mots qui ont
déclenché la détection appartiennent-ils au libellé ou aux synonymes de
l'indicateur retenu ?

    rapport_masculinite   synonymes : « ratio hommes femmes »,
                          « proportion d'hommes », « équilibre hommes
                          femmes »          -> les mots nomment
                                               l'indicateur, on retire
                                               le filtre

    menages               synonymes : « ménages », « foyers »…
                          aucun mot de sexe -> la ventilation est
                                               demandée, on la garde et
                                               le moteur refuse

La règle ne s'applique qu'aux indicateurs qui ne déclarent PAS la
dimension. Si un indicateur déclare `sexe`, le filtre est légitime et
passe sans examen — c'est le cas de `pop_totale`.


UNE VALEUR QUI DÉSIGNE LE TOUT N'EST PAS UN FILTRE

Constaté sur deux évolutions qui avaient par ailleurs un plan correct :

    evolution · taux_chomage_a · par region · DAKAR · {age: TOUT}
    -> serie_trop_courte

    evolution · pop_region · par departement · DAKAR · {age: TOUT}
    -> serie_trop_courte

Le moteur filtrait sur une valeur absente de toute observation, la série
tombait à zéro point, et il refusait pour série trop courte — un refus
exact sur le plan reçu, et faux sur la question posée. Ces deux-là sont
les plus coûteuses à diagnostiquer : rien dans le motif ne désigne le
filtre.

« TOUT », « TOUS », « TOTAL », « ENSEMBLE », « ALL » expriment l'absence
de ventilation, par définition. Aucun code de modalité réel ne leur
ressemble : les nôtres sont M, F, U, R et les codes d'âge SDMX. La liste
est donc fermée, et ces filtres sont retirés.


UNE ANNÉE N'EST PAS UNE MODALITÉ

Même question, autre valeur inventée :

    evolution · taux_chomage_a · par region · DAKAR
      periode 2015 à —  ·  {age: Y2015}
    -> serie_trop_courte

« depuis 2015 » a produit à la fois la bonne période et un code de
tranche d'âge fabriqué à partir de l'année. Comme `age` EST une dimension
déclarée du chômage, et que `Y2015` n'est pas une valeur totale, les deux
règles précédentes le laissaient passer.

Le temps est porté par `periode`, jamais par `filtres`. Et la forme est
sans ambiguïté : quatre chiffres, éventuellement précédés d'un Y. Les
vrais codes d'âge SDMX portent tous un séparateur — `Y15T24`, `Y0T4`,
`Y_GE65` — et aucun ne peut être confondu avec une année.


UNE CLÉ INVENTÉE PAR LE MODÈLE DOIT ÊTRE DÉCLARÉE

Relevé dans une même série de quinze questions : `{pop_region: Dakar}`,
`dimension: dakar`, `dimension: mbour`, `dimension: 2020`,
`dimension: date`, `dimension: annee`. Le modèle remplit ces deux champs
avec ce qu'il a sous la main — un code d'indicateur, un nom de zone, une
année.

Un filtre portant sur une dimension que l'indicateur ne déclare pas ne
peut produire aucune donnée. Il ne peut que provoquer un refus. Les
refus que l'on veut conserver ne viennent pas de là : ils viennent des
clés détectées dans la QUESTION, par le vocabulaire fermé ci-dessous.

D'où l'asymétrie, qui est le cœur de ce module :

    clé venue de la question   -> conservée même si non déclarée,
                                  c'est elle qui porte le refus

    clé venue du modèle seul   -> conservée seulement si déclarée,
                                  sinon retirée

La comparaison tolère le singulier et le pluriel, pour ne pas écarter
`secteurs` quand l'indicateur déclare `secteur`.
"""

import re
import unicodedata

# Dimensions reconnues ici. Celles du modèle portant sur d'autres
# dimensions sont examinées, mais pas devinées.
DETECTABLES = {"sexe", "milieu"}

# Clés jamais légitimes dans `filtres` ni dans `dimension` : ce sont des
# niveaux géographiques, portés par `niveau` et `zones`.
GEOGRAPHIQUES = {"national", "region", "regions", "departement",
                 "departements", "commune", "communes", "quartier",
                 "quartiers", "zone", "zones", "geographie", "geographique"}

# Même raison, pour le temps : il est porté par `periode`.
TEMPORELLES = {"annee", "annees", "an", "ans", "temps", "periode",
               "periodes", "date", "dates", "millesime", "exercice",
               "evolution", "tendance"}

# Valeurs de filtre qui expriment l'absence de filtre. Aucune n'est un
# code de modalité réel : les nôtres sont M, F, U, R et les codes d'âge
# SDMX.
VALEURS_TOTALES = {
    "tout", "tous", "toute", "toutes", "total", "totaux", "totale",
    "ensemble", "global", "globale", "all", "any", "aucun", "aucune",
    "null", "none", "na", "n a", "indifferent", "indifferente",
    "les deux", "tous les deux", "sans filtre", "non precise",
    "non specifie", "confondus", "cumule", "cumules",
}

MOTS = [
    (("feminin", "feminine", "feminines", "femme", "femmes", "fille",
      "filles", "dirige par une femme", "dirigees par des femmes"),
     ("sexe", "F")),
    (("masculin", "masculine", "masculines", "homme", "hommes", "garcon",
      "garcons", "dirige par un homme"),
     ("sexe", "M")),
    (("urbain", "urbaine", "urbaines", "en ville", "milieu urbain",
      "zones urbaines"),
     ("milieu", "U")),
    (("rural", "rurale", "rurales", "campagne", "milieu rural",
      "zones rurales"),
     ("milieu", "R")),
]


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _compacte(s):
    return _norm(s).replace(" ", "")


def _rejetee(cle):
    """Clé qui ne peut jamais être une ventilation : géographie ou temps."""
    c = _compacte(cle)
    return c in GEOGRAPHIQUES or c in TEMPORELLES


def _valeur_totale(valeur):
    """La valeur exprime-t-elle l'absence de ventilation ?"""
    if valeur is None:
        return True
    n = _norm(valeur)
    return n == "" or n in VALEURS_TOTALES


def _valeur_annee(valeur):
    """
    La valeur est-elle une année déguisée en modalité ?

    Quatre chiffres, éventuellement précédés d'un Y. Les codes d'âge SDMX
    portent tous un séparateur — Y15T24, Y0T4, Y_GE65 — et ne peuvent donc
    pas être pris pour des années.
    """
    n = _norm(valeur).replace(" ", "")
    m = re.fullmatch(r"y?(\d{4})", n)
    return bool(m) and 1900 <= int(m.group(1)) <= 2100


def _declaree(cle, dimensions):
    """
    La clé figure-t-elle parmi les dimensions déclarées de l'indicateur ?

    Singulier et pluriel sont acceptés de part et d'autre : le modèle
    écrit « secteurs » là où le catalogue déclare « secteur », et ce
    n'est pas une erreur de fond.
    """
    n = _compacte(cle)
    if not n:
        return False
    for d in dimensions or ():
        m = _compacte(d)
        if n == m:
            return True
        if len(n) >= 4 and len(m) >= 4 and (n.startswith(m) or m.startswith(n)):
            return True
    return False


def filtres_cites(question):
    """
    Ventilations nommées dans la question, parmi celles que l'on sait
    reconnaître.

    Une dimension ne peut recevoir qu'une valeur : « hommes et femmes »
    ne produit aucun filtre, puisque la demande porte alors sur
    l'ensemble.

    Retourne aussi, pour chaque dimension, les mots qui l'ont déclenchée :
    ils servent à distinguer une ventilation demandée d'un indicateur
    nommé.
    """
    texte = f" {_norm(question)} "

    trouves, declencheurs, conflits = {}, {}, set()
    for motifs, (cle, valeur) in MOTS:
        vus = [m for m in motifs if f" {m} " in texte]
        if not vus:
            continue
        if cle in trouves and trouves[cle] != valeur:
            conflits.add(cle)
        trouves[cle] = valeur
        declencheurs.setdefault(cle, []).extend(vus)

    for cle in conflits:
        trouves.pop(cle, None)
        declencheurs.pop(cle, None)
    return trouves, declencheurs


def _fiche_indicateur(code):
    """
    Libellé et synonymes de l'indicateur, normalisés, ou None.

    Lecture seule et tolérante : si le code n'existe pas au catalogue,
    c'est au moteur de le refuser, pas à cette fonction d'échouer.
    """
    if not code:
        return None
    try:
        from catalog.models import Indicateur
        i = Indicateur.objects.filter(code=code).only(
            "libelle", "synonymes", "dimensions").first()
    except Exception:
        return None
    if i is None:
        return None
    return {
        "texte": _norm(i.libelle + " " + " ".join(i.synonymes or [])),
        "dimensions": set(i.dimensions or []),
    }


def corriger_filtres(plan, question):
    """
    Complète les filtres du plan par ceux réellement cités, et retire
    ceux qui ne peuvent pas en être.

    Ce que la question nomme fait autorité sur les dimensions
    détectables ; ce que le modèle a proposé sur les autres n'est
    conservé que si l'indicateur le déclare.

    Le but est de rendre au moteur de quoi refuser : un filtre absent du
    plan est un refus qui n'aura pas lieu. Mais un filtre que le plan
    n'aurait jamais dû porter est un refus qui n'aurait pas dû avoir
    lieu — et c'est le plus coûteux des deux, parce que le motif rendu ne
    désigne jamais le filtre fautif.
    """
    cites, declencheurs = filtres_cites(question)
    existants = dict(plan.get("filtres") or {})

    # Une valeur qui désigne le tout exprime l'absence de filtre ; une
    # année désigne une période, portée par `periode`.
    for cle in list(existants):
        if _valeur_totale(existants[cle]) or _valeur_annee(existants[cle]):
            existants.pop(cle)

    # Géographie et temps : jamais des ventilations.
    for cle in list(existants):
        if _rejetee(cle):
            existants.pop(cle)

    fiche = _fiche_indicateur(plan.get("indicateur"))
    if fiche:
        # Les mots qui appartiennent à la définition de l'indicateur le
        # nomment ; ils ne demandent pas de le découper.
        for cle in list(cites):
            if cle in fiche["dimensions"]:
                continue          # ventilation déclarée : filtre légitime
            mots = declencheurs.get(cle) or []
            if any(f" {m} " in f" {fiche['texte']} " for m in mots):
                cites.pop(cle)    # le mot nomme l'indicateur
                existants.pop(cle, None)

        # Une clé que seul le modèle propose doit être déclarée. Celles
        # venues de la question restent, même non déclarées : ce sont
        # elles qui portent les refus légitimes.
        for cle in list(existants):
            if cle in cites:
                continue
            if not _declaree(cle, fiche["dimensions"]):
                existants.pop(cle)

    # Les dimensions détectables sont reprises de la question, y compris
    # pour effacer un filtre que le modèle aurait inventé. On ne touche
    # qu'à celles qui ont survécu aux tests précédents.
    for cle in DETECTABLES & set(cites):
        existants.pop(cle, None)
    existants.update(cites)

    plan["filtres"] = existants

    # Même examen pour la dimension d'une répartition : « répartition par
    # région » est une carte ou un classement ; « dimension: annee » est
    # l'axe d'une évolution ; un nom de zone ou une année n'est ni l'un ni
    # l'autre.
    d = plan.get("dimension")
    if d:
        if _rejetee(d) or _valeur_totale(d) or _valeur_annee(d):
            plan["dimension"] = None
        elif fiche and not _declaree(d, fiche["dimensions"]):
            plan["dimension"] = None

    return plan