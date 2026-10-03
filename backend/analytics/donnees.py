"""
backend/analytics/donnees.py

StatSense AI — Accès aux observations

Deux problèmes que toutes les méthodes rencontrent, résolus ici une fois :

1. AGRÉGATION HIÉRARCHIQUE
   Les données du recensement sont stockées au niveau quartier. Une
   question au niveau région doit donc sommer les quartiers qui en
   dépendent. L'agrégation n'est licite que pour un indicateur
   agrégeable : un taux ne se somme pas entre zones.

2. INDICATEURS DÉRIVÉS
   La taille moyenne des ménages, le rapport de masculinité et les
   ménages par concession ne sont pas stockés : ils se calculent à la
   volée. Point important : le calcul se fait APRÈS agrégation des
   composants, jamais en moyennant les ratios des quartiers — sinon un
   quartier de 30 habitants pèserait autant qu'un quartier de 30 000.


UNE REQUÊTE PAR NIVEAU, PAS UNE PAR ZONE

La version précédente exposait `valeurs_par_zone`, qui bouclait sur les
zones et appelait `valeur()` pour chacune : une requête SQL par zone, deux
pour un indicateur dérivé. Au niveau région, quatorze zones, personne ne
s'en apercevait. Au niveau quartier, vingt-cinq mille deux cent
quarante-et-une zones : « Où les ménages sont-ils les plus grands ? »
demandait 265 secondes, presque toutes passées en allers-retours avec
PostgreSQL.

Le remède tient à la forme de la hiérarchie. `Zone.parent` chaîne
quartier → commune → département → région, donc remonter un quartier à sa
région est une affaire de trois jointures, et l'agrégation de tous les
quartiers vers toutes les régions tient dans UNE requête :

    Observation.objects
        .filter(indicateur=…, periode=…, dims=…, zone__niveau=QUARTIER)
        .values("zone__parent__parent__parent_id")
        .annotate(t=Sum("valeur"))

Le nombre de sauts se déduit de l'écart entre les deux niveaux dans
ORDRE. La règle « descendre niveau par niveau et s'arrêter au premier qui
porte des données » est conservée : elle évite de compter deux fois une
valeur stockée à la fois sur la commune et sur ses quartiers.

`valeur()` reste disponible pour une zone unique — valeur_simple et
evolution en font quelques appels, pas vingt-cinq mille.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from catalog.models import Indicateur
from geography.models import Niveau, Zone
from observations.models import Observation

from .resultats import ErreurAnalyse

# Ordre du plus large au plus fin. Sert à savoir si l'on peut descendre,
# et de combien de jointures il faut remonter.
ORDRE = [Niveau.NATIONAL, Niveau.REGION, Niveau.DEPARTEMENT,
         Niveau.COMMUNE, Niveau.QUARTIER]

# --- indicateurs dérivés : composants et formule --------------------------
DERIVES = {
    "taille_menage": {
        "composants": [("pop_totale", {}), ("menages", {})],
        "calcul": lambda p, m: (p / m) if m else None,
        "unite": "personnes par ménage",
    },
    "menages_par_concession": {
        "composants": [("menages", {}), ("concessions", {})],
        "calcul": lambda m, c: (m / c) if c else None,
        "unite": "ménages par concession",
    },
    "rapport_masculinite": {
        "composants": [("pop_totale", {"sexe": "H"}),
                       ("pop_totale", {"sexe": "F"})],
        "calcul": lambda h, f: (h / f * 100) if f else None,
        "unite": "hommes pour 100 femmes",
    },
}


def get_indicateur(code):
    ind = Indicateur.objects.select_related("source").filter(code=code).first()
    if ind is None:
        raise ErreurAnalyse(
            f"L'indicateur « {code} » ne figure pas dans le catalogue.",
            motif="indicateur_absent",
        )
    return ind


def verifier_granularite(ind, niveau):
    """
    Empêche de fabriquer une ventilation géographique inexistante.

    Un indicateur publié au niveau national ne peut pas être affiché par
    région : on refuse plutôt que de diviser l'agrégat.
    """
    if niveau is None:
        return
    dispo, demande = ind.granularite_geo_min, niveau
    if dispo not in ORDRE or demande not in ORDRE:
        return
    if ORDRE.index(demande) > ORDRE.index(dispo):
        raise ErreurAnalyse(
            f"« {ind.libelle} » n'est disponible qu'au niveau {dispo}.",
            motif="granularite_indisponible",
            alternatives=[f"{ind.libelle} au niveau {dispo}"],
        )


def verifier_dimensions(ind, filtres):
    inconnues = set(filtres or {}) - set(ind.dimensions or [])
    if inconnues:
        raise ErreurAnalyse(
            f"La ventilation {sorted(inconnues)} n'existe pas pour "
            f"« {ind.libelle} ».",
            motif="dimension_invalide",
            alternatives=[f"ventilations disponibles : {ind.dimensions}"]
            if ind.dimensions else ["aucune ventilation disponible"],
        )


def periodes_disponibles(ind):
    """
    Un indicateur dérivé n'a pas d'observation propre : ses périodes
    sont celles de ses composants.
    """
    if ind.code in DERIVES:
        code, _ = DERIVES[ind.code]["composants"][0]
        comp = Indicateur.objects.filter(code=code).first()
        if comp is None:
            return []
        ind = comp

    return sorted(
        Observation.objects.filter(indicateur=ind)
        .values_list("periode", flat=True).distinct()
    )


# --- lecture d'une zone unique --------------------------------------------

def _valeur_directe(ind, zone, periode, filtres):
    """Observation stockée exactement sur cette zone."""
    o = Observation.objects.filter(
        indicateur=ind, zone=zone, periode=periode, dims=filtres or {}
    ).first()
    return o.valeur if o else None


def _valeur_agregee(ind, zone, periode, filtres):
    """
    Somme des descendants, au niveau le plus fin où la donnée existe.

    On descend niveau par niveau plutôt que de sommer tous les
    descendants d'un coup : sinon une valeur stockée à la fois sur la
    commune et sur ses quartiers serait comptée deux fois.
    """
    if not ind.agregeable:
        return None

    depart = ORDRE.index(zone.niveau) if zone.niveau in ORDRE else 0
    for niveau in ORDRE[depart + 1:]:
        total = Observation.objects.filter(
            indicateur=ind, periode=periode, dims=filtres or {},
            zone__code__startswith=f"{zone.code}-",
            zone__niveau=niveau,
        ).aggregate(t=Sum("valeur"))["t"]
        if total is not None:
            return total
    return None


def valeur(ind, zone, periode, filtres=None):
    """
    Valeur d'un indicateur pour UNE zone : directe si elle existe,
    agrégée depuis les descendants sinon.

    Pour une liste de zones, utiliser `valeurs_par_zone`, qui fait le
    même travail en un nombre de requêtes constant.
    """
    if ind.code in DERIVES:
        return _valeur_derivee(ind, zone, periode, filtres)

    v = _valeur_directe(ind, zone, periode, filtres)
    if v is not None:
        return v
    return _valeur_agregee(ind, zone, periode, filtres)


def _valeur_derivee(ind, zone, periode, filtres=None):
    """
    Calcule un indicateur dérivé APRÈS agrégation de ses composants.

    C'est la différence entre « la taille moyenne des ménages de Dakar »
    (population totale / ménages totaux) et « la moyenne des tailles de
    ménage des quartiers de Dakar », qui serait fausse.
    """
    spec = DERIVES[ind.code]
    valeurs = []
    for code, dims in spec["composants"]:
        comp = Indicateur.objects.filter(code=code).first()
        if comp is None:
            return None
        v = _valeur_directe(comp, zone, periode, dims)
        if v is None:
            v = _valeur_agregee(comp, zone, periode, dims)
        if v is None:
            return None
        valeurs.append(Decimal(v))
    return _arrondir(spec["calcul"](*valeurs))


def _arrondir(v):
    if v is None:
        return None
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- lecture en masse ------------------------------------------------------

def _champ_ancetre(sauts):
    """
    Chemin ORM du n-ième ancêtre d'une observation.

        1 saut  -> zone__parent_id
        2 sauts -> zone__parent__parent_id
        3 sauts -> zone__parent__parent__parent_id
    """
    return "zone" + "__parent" * (sauts - 1) + "__parent_id"


def _map_directe(ind, ids, niveaux, periode, dims):
    """Valeurs stockées exactement sur les zones demandées."""
    brut = Observation.objects.filter(
        indicateur=ind, periode=periode, dims=dims,
        zone__niveau__in=niveaux,
    ).values_list("zone_id", "valeur")
    vises = set(ids)
    return {zid: v for zid, v in brut if zid in vises}


def _map_agregee(ind, ids, niveau_cible, periode, dims):
    """
    Somme des descendants pour toutes les zones d'un niveau, en une
    requête par niveau descendu.

    S'arrête au premier niveau qui porte des observations, pour la même
    raison que la version mono-zone : une valeur présente à la fois sur la
    commune et sur ses quartiers serait comptée deux fois.
    """
    if not ind.agregeable or niveau_cible not in ORDRE:
        return {}

    depart = ORDRE.index(niveau_cible)
    vises = set(ids)

    for i in range(depart + 1, len(ORDRE)):
        champ = _champ_ancetre(i - depart)
        lignes = (
            Observation.objects
            .filter(indicateur=ind, periode=periode, dims=dims,
                    zone__niveau=ORDRE[i])
            .values(champ)
            .annotate(t=Sum("valeur"))
        )
        trouve = {r[champ]: r["t"] for r in lignes
                  if r[champ] in vises and r["t"] is not None}
        if trouve:
            return trouve
    return {}


def _map_valeurs(ind, zones, periode, dims):
    """
    zone_id -> valeur, pour un indicateur STOCKÉ.

    Directes d'abord, agrégées ensuite pour les zones restées sans
    valeur. Nombre de requêtes indépendant du nombre de zones.
    """
    ids = [z.id for z in zones]
    niveaux = {z.niveau for z in zones}

    out = _map_directe(ind, ids, niveaux, periode, dims)

    restants = [z for z in zones if z.id not in out]
    if not restants:
        return out

    # Les zones sans valeur directe sont regroupées par niveau : une
    # passe d'agrégation par niveau présent, pas par zone.
    for niveau in {z.niveau for z in restants}:
        cibles = [z.id for z in restants if z.niveau == niveau]
        out.update(_map_agregee(ind, cibles, niveau, periode, dims))

    return out


def valeurs_par_zone(ind, zones, periode, filtres=None):
    """
    Valeur pour chaque zone d'une liste. Les zones sans donnée sont
    omises — et signalées à l'appelant, qui en fait une note.

    Nombre de requêtes constant, quel que soit le nombre de zones : c'est
    ce qui rend un classement au niveau quartier praticable.
    """
    zones = list(zones)
    if not zones:
        return [], []

    dims = filtres or {}

    if ind.code in DERIVES:
        spec = DERIVES[ind.code]
        cartes = []
        for code, d in spec["composants"]:
            comp = Indicateur.objects.filter(code=code).first()
            if comp is None:
                return [], [z.nom for z in zones]
            cartes.append(_map_valeurs(comp, zones, periode, d))

        valeurs = {}
        for z in zones:
            composants = [c.get(z.id) for c in cartes]
            if any(x is None for x in composants):
                continue
            v = spec["calcul"](*[Decimal(x) for x in composants])
            if v is not None:
                valeurs[z.id] = _arrondir(v)
    else:
        valeurs = _map_valeurs(ind, zones, periode, dims)

    out, manquantes = [], []
    for z in zones:
        v = valeurs.get(z.id)
        if v is None:
            manquantes.append(z.nom)
        else:
            out.append({"zone": z.nom, "code": z.code,
                        "geojson_id": z.geojson_id, "valeur": v})
    return out, manquantes


# --- résolution des zones --------------------------------------------------

def resoudre_zones(niveau=None, noms=None, parent=None):
    """
    Traduit la partie géographique d'un plan en objets Zone.

    `noms` accepte un nom de zone ou un code. La recherche est insensible
    aux accents et à la casse, via la normalisation appliquée au
    chargement.
    """
    qs = Zone.objects.all()
    if niveau:
        qs = qs.filter(niveau=niveau)
    if parent is not None:
        qs = qs.filter(code__startswith=f"{parent.code}-")
    if noms:
        return [zone_par_nom(n) for n in noms]
    return list(qs)


def zone_par_nom(nom):
    """Résout un nom ou un code de zone en une Zone, ou lève une erreur."""
    import unicodedata

    def _n(s):
        s = unicodedata.normalize("NFD", str(s))
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return s.upper().strip()

    cible = _n(nom)
    candidats = [z for z in Zone.objects.all() if _n(z.nom) == cible]
    if not candidats:
        candidats = list(Zone.objects.filter(code=nom))
    if not candidats:
        raise ErreurAnalyse(
            f"Zone « {nom} » introuvable.", motif="zone_inconnue",
        )
    # Ambiguïté fréquente : « Dakar » est à la fois région et département.
    # On privilégie le niveau le plus large.
    candidats.sort(key=lambda z: ORDRE.index(z.niveau)
                   if z.niveau in ORDRE else 99)
    return candidats[0]