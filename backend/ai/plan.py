"""
backend/ai/plan.py

StatSense AI — Le QueryPlan

C'est le contrat entre le modèle et le moteur. Le modèle ne produit rien
d'autre ; le moteur ne traite rien d'autre. Ni l'un ni l'autre ne connaît
le fonctionnement interne de l'autre.

La validation faite ici porte sur la FORME. La validation portant sur les
DONNÉES — existence de l'indicateur, ventilations réelles, période
couverte — est faite par le moteur, qui seul connaît le contenu de la
base.

Principe de répartition entre les deux : on ne rejette ici que ce qui
rend le plan inexploitable. Un code d'indicateur mal orthographié est
normalisé et transmis ; s'il n'existe pas, c'est au moteur de le dire
avec un refus explicite.


CE QUI N'EST PLUS UNE ERREUR DE FORME

`methode` ne l'est plus. Elle était rejetée quand le modèle l'omettait,
ce qui coûtait deux appels au modèle puis un repli déterministe :

    « Quelles régions sont les moins peuplées ? »
        -> methode: null, deux fois
        -> Plan inexploitable après deux essais

Une liste de cinq valeurs est une forme fermée : elle appartient au code.
`valider()` normalise donc ce que le modèle propose, laisse le champ à
None s'il est absent ou inconnu, et `corriger_cadrage` le déduit de la
question — « les moins peuplées » annonce un classement.

Le champ n'a pas disparu du schéma pour autant : le modèle sait lire
l'intention derrière « montre-moi ça sur une carte », et cette intention
n'est pas déductible d'un mot-clé seul. Il propose, le code comble.

Conséquence sur les compléments de cohérence en fin de fonction : ils
dépendent de la méthode, donc ils ne s'appliquent ici que si le modèle en
a fourni une. Sinon c'est `corriger_cadrage` qui les applique, après avoir
rempli le champ.
"""

import re
import unicodedata

from .cadrage import METHODES, methode_citee

NIVEAUX = {"national", "region", "departement", "commune", "quartier"}
ORDRES = {"desc", "asc"}

SYNONYMES_NIVEAU = {
    "regionale": "region", "régionale": "region", "regional": "region",
    "régional": "region", "regions": "region", "régions": "region",
    "departemental": "departement", "départemental": "departement",
    "departements": "departement", "départements": "departement",
    "communal": "commune", "communes": "commune",
    "quartiers": "quartier", "pays": "national", "senegal": "national",
    "sénégal": "national", "nationale": "national", "geographique": "region",
}

SYNONYMES_ORDRE = {
    "croissant": "asc", "ascendant": "asc", "montant": "asc",
    "decroissant": "desc", "décroissant": "desc", "descendant": "desc",
    "haut": "desc", "bas": "asc",
}


class PlanInvalide(Exception):
    def __init__(self, message, champ=None):
        super().__init__(message)
        self.message = message
        self.champ = champ


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def _slug(s):
    """
    Ramène un code d'indicateur à la forme du catalogue.

    Le modèle écrit parfois « taux_alphabétisation » ou « Pop_Totale ».
    L'accent et la majuscule ne sont pas des erreurs de forme : on
    normalise et on transmet. Si le code obtenu n'existe pas au
    catalogue, le moteur le refusera explicitement — ce qui vaut mieux
    qu'un rejet ici, suivi d'un repli qui répondrait autre chose.
    """
    return re.sub(r"[^a-z0-9_]+", "_", _norm(s)).strip("_")


def _entier(v, defaut=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return defaut


def valider(brut):
    """
    Normalise et valide la forme du plan. Lève PlanInvalide avec un
    message exploitable : ce message est réinjecté au modèle pour un
    unique nouvel essai.
    """
    if not isinstance(brut, dict):
        raise PlanInvalide("Le plan n'est pas un objet JSON.")

    plan = {}

    # --- méthode ---
    # Forme fermée de cinq valeurs, donc du ressort du code. Une valeur
    # absente ou inconnue n'est pas une erreur de forme : corriger_cadrage
    # la déduira de la question.
    methode = _norm(brut.get("methode")).replace("-", "_").replace(" ", "_")
    plan["methode"] = methode if methode in METHODES else None

    # --- indicateur ---
    code = brut.get("indicateur")
    plan["indicateur"] = (_slug(code) or None) if code not in (
        None, "", "null") else None

    # --- zones ---
    zones = brut.get("zones") or []
    if isinstance(zones, str):
        zones = [zones]
    plan["zones"] = [str(z).strip() for z in zones if str(z).strip()]

    # --- niveau ---
    niveau = _norm(brut.get("niveau"))
    niveau = SYNONYMES_NIVEAU.get(niveau, niveau)
    if niveau and niveau not in NIVEAUX:
        raise PlanInvalide(
            f"niveau « {brut.get('niveau')} » inconnu. "
            f"Valeurs permises : {', '.join(sorted(NIVEAUX))}.",
            champ="niveau",
        )
    plan["niveau"] = niveau or None

    # --- période ---
    p = brut.get("periode") or {}
    if not isinstance(p, dict):
        p = {}
    plan["periode"] = {
        "debut": p.get("debut") if p.get("debut") not in ("", "null") else None,
        "fin": p.get("fin") if p.get("fin") not in ("", "null") else None,
    }

    # --- filtres ---
    filtres = brut.get("filtres") or {}
    if not isinstance(filtres, dict):
        filtres = {}
    plan["filtres"] = {str(k): str(v) for k, v in filtres.items()
                       if v not in (None, "", "null", "_T")}

    # --- dimension de répartition ---
    d = brut.get("dimension")
    plan["dimension"] = (_slug(d) or None) if d not in (
        None, "", "null") else None

    # --- top_n et ordre ---
    plan["top_n"] = _entier(brut.get("top_n"))
    ordre = _norm(brut.get("ordre"))
    plan["ordre"] = SYNONYMES_ORDRE.get(ordre, ordre if ordre in ORDRES
                                        else "desc")

    # --- confiance et clarification ---
    try:
        plan["confiance"] = max(0.0, min(1.0,
                                         float(brut.get("confiance", 0.5))))
    except (TypeError, ValueError):
        plan["confiance"] = 0.5

    c = brut.get("clarification")
    plan["clarification"] = str(c).strip() if c not in (
        None, "", "null") else None

    # --- cohérences internes ---
    # Elles dépendent de la méthode : elles ne s'appliquent donc que si le
    # modèle en a fourni une. Dans le cas contraire, corriger_cadrage les
    # applique après avoir rempli le champ.
    if plan["methode"] == "geographique":
        plan["niveau"] = plan["niveau"] or "region"
    if plan["methode"] == "repartition":
        plan["niveau"] = plan["niveau"] or "national"
    if plan["methode"] == "classement":
        plan["niveau"] = plan["niveau"] or "region"
        plan["top_n"] = plan["top_n"] or 10

    if plan["indicateur"] is None and not plan["clarification"]:
        plan["clarification"] = "Quel indicateur souhaitez-vous consulter ?"

    return plan


# ---------------------------------------------------------------------------
# REPLI DÉTERMINISTE
# ---------------------------------------------------------------------------
#
# Sert au seul cas où le modèle est INJOIGNABLE. Il garde la plateforme
# utilisable pendant une panne, mais il ne doit jamais devenir devin :
# répondre à côté est pire que ne pas répondre, et c'est vrai à plus
# forte raison sur une plateforme dont l'argument est l'exactitude.
#
# Trois précautions, tirées d'une panne réelle où le repli avait répondu
# « taux de mortalité » à une question sur l'alphabétisation :
#
#   1. l'indicateur n'est retenu que s'il ressemble vraiment à la
#      question ; en dessous du seuil, on demande une précision ;
#   2. l'année citée est extraite, pour que le moteur puisse refuser une
#      période non couverte ;
#   3. les ventilations évidentes sont reconnues, pour que le moteur
#      puisse refuser une dimension indisponible.
#
# Ces trois points rendent au repli les refus que le modèle aurait
# produits.
#
# La méthode, elle, est déduite par `methode_citee` — la même fonction que
# dans le chemin normal. Le repli n'a plus sa propre table de mots-clés :
# une seule, dans cadrage.py, et un mot ajouté là profite aux deux.

# Proximité minimale exigée pour retenir un indicateur sans le modèle.
# Calibré sur les mesures : un bon appariement dépasse 0,10, le bruit
# plafonne autour de 0,05.
SEUIL_REPLI = 0.55

# Ventilations reconnaissables sans modèle. Le moteur refusera celles qui
# ne sont pas déclarées pour l'indicateur retenu.
FILTRES_MOTS = [
    (("feminin", "feminine", "femme", "femmes", "filles"), ("sexe", "F")),
    (("masculin", "masculine", "homme", "hommes", "garcons"), ("sexe", "M")),
    (("urbain", "urbaine", "ville", "villes"), ("milieu", "U")),
    (("rural", "rurale", "campagne", "campagnes"), ("milieu", "R")),
]


def repli(question, indicateurs):
    """
    Construit un plan sans modèle, par mots-clés.

    Retourne un plan portant `clarification` lorsque aucun indicateur ne
    ressemble assez à la question : mieux vaut demander une précision
    que retenir le premier venu.
    """
    from .recherche import scores

    q = _norm(question)

    methode = methode_citee(question) or "valeur_simple"

    # --- indicateur, sous condition de ressemblance ---
    classement = scores(question)
    code, meilleur = None, 0.0
    for i in indicateurs:
        s = classement.get(i.code, 0.0)
        if s > meilleur:
            code, meilleur = i.code, s

    if meilleur < SEUIL_REPLI:
        return valider({
            "methode": methode, "indicateur": None, "zones": [],
            "niveau": None, "periode": {"debut": None, "fin": None},
            "filtres": {}, "dimension": None, "top_n": None,
            "ordre": "desc", "confiance": 0.1,
            "clarification": "Aucun indicateur disponible ne correspond "
                             "clairement à cette question.",
        })

    # --- zones ---
    zones = []
    from geography.models import Niveau, Zone
    for z in Zone.objects.filter(
        niveau__in=[Niveau.REGION, Niveau.DEPARTEMENT, Niveau.NATIONAL]
    ):
        if _norm(z.nom) in q:
            zones.append(z.nom)
    zones = zones[:2]

    # --- période citée ---
    # Sans elle, « la population de Dakar en 2010 » recevrait la valeur
    # de 2023 sans que rien ne signale le glissement.
    annee = re.search(r"\b(?:19|20)\d{2}\b", q)
    periode = {"debut": None, "fin": int(annee.group(0))} if annee \
        else {"debut": None, "fin": None}

    # --- ventilations évidentes ---
    filtres = {}
    for motifs, (cle, valeur) in FILTRES_MOTS:
        if any(f" {m}" in f" {q}" for m in motifs):
            filtres[cle] = valeur

    n = re.search(r"\b(\d{1,2})\b", q)
    top_n = int(n.group(1)) if n and methode == "classement" else None

    return valider({
        "methode": methode,
        "indicateur": code,
        "zones": zones,
        "niveau": "region" if not zones else None,
        "periode": periode,
        "filtres": filtres,
        "dimension": None,
        "top_n": top_n,
        "ordre": "asc" if "moins" in q else "desc",
        "confiance": 0.45,
        "clarification": None,
    })


# Codes inventés par le modèle pour « combien de femmes » : ce sont des
# ventilations de la population, pas des indicateurs.
RE_POP_SEXE = re.compile(
    r"^(?:pop|population|nombre|nb|effectif)s?(?:_totale)?_(?:des_)?"
    r"(?:femmes?|hommes?|feminine|masculine)s?$")

# Mots qui demandent réellement un rapport entre les sexes.
MOTS_RAPPORT = ("rapport", "ratio", "proportion", "equilibre", "plus d",
                "autant", "masculinite")


def corriger_indicateur(plan, question):
    """
    Deux erreurs mesurées du modèle sur les questions de sexe :

        « Combien de femmes vivent à Dakar ? »  -> pop_femmes (inventé)
        « Combien d'hommes vivent à Dakar ? »   -> rapport_masculinite

    La première produisait un refus injustifié, la seconde un ratio à qui
    demandait un effectif. Une question qui nomme UN seul sexe sans parler
    de rapport demande la population de ce sexe.
    """
    from .filtres import filtres_cites

    code = plan.get("indicateur") or ""
    un_sexe = "sexe" in filtres_cites(question)[0]
    texte = _norm(question)

    if RE_POP_SEXE.match(code):
        plan["indicateur"] = "pop_totale"
    elif (code == "rapport_masculinite" and un_sexe
          and not any(m in texte for m in MOTS_RAPPORT)):
        plan["indicateur"] = "pop_totale"
    return plan