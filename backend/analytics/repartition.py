"""
backend/analytics/repartition.py

StatSense AI — Méthode « répartition »

Décompose un total selon une de ses ventilations. Sur la population
ventilée par âge, c'est la pyramide des âges ; sur l'emploi, la part de
chaque secteur d'activité.

Deux précautions propres à cette méthode :

  - Une répartition n'a de sens que sur un indicateur agrégeable. On ne
    « répartit » pas un taux : additionner des pourcentages entre
    modalités ne produit rien d'interprétable.

  - Les observations plus finement ventilées que la demande sont
    écartées, sans quoi une population comptée à la fois par âge et par
    sexe serait comptée deux fois. Les fichiers SDMX traduisent la
    convention « toutes catégories » par l'absence de la dimension : une
    observation ventilée uniquement par âge ne porte pas de sexe, et
    c'est elle que l'on retient.
"""

from decimal import Decimal

from observations.models import Observation

from .donnees import (
    get_indicateur,
    verifier_dimensions,
    verifier_granularite,
    zone_par_nom,
)
from .resultats import AnalysisResult, ErreurAnalyse, source_de

MAX_MODALITES = 40


def repartition(plan):
    from geography.models import Niveau, Zone

    from .moteur import _periode, _prepare

    ind, filtres = _prepare(plan)
    periode = _periode(ind, plan)

    if not ind.agregeable:
        raise ErreurAnalyse(
            f"« {ind.libelle} » est un {ind.unite.strip() or 'taux'} : "
            f"une répartition supposerait d'additionner ses valeurs entre "
            f"catégories, ce qui n'aurait pas de sens.",
            motif="non_agregeable",
            alternatives=[f"évolution de {ind.libelle}",
                          f"classement par {ind.libelle}"],
        )

    noms = plan.get("zones") or []
    zone = (zone_par_nom(noms[0]) if noms
            else Zone.objects.filter(niveau=Niveau.NATIONAL).first())
    if zone is None:
        raise ErreurAnalyse("Aucune zone précisée.", motif="zone_manquante")

    # Dimension de répartition : celle demandée, ou la première déclarée
    # au catalogue. Une dimension déjà filtrée ne peut pas servir d'axe.
    candidates = [d for d in (ind.dimensions or []) if d not in filtres]
    dimension = plan.get("dimension")
    if dimension and dimension not in candidates:
        dimension = None
    dimension = dimension or (candidates[0] if candidates else None)

    if dimension is None:
        raise ErreurAnalyse(
            f"« {ind.libelle} » ne comporte aucune ventilation à répartir.",
            motif="dimension_invalide",
            alternatives=[f"valeur de {ind.libelle}",
                          f"évolution de {ind.libelle}"],
        )

    totaux = {}
    for o in Observation.objects.filter(
        indicateur=ind, zone=zone, periode=periode
    ).only("dims", "valeur"):
        dims = o.dims or {}
        modalite = dims.get(dimension)
        if modalite is None:
            continue
        if any(dims.get(k) != v for k, v in filtres.items()):
            continue
        # Écarte les observations plus fines que la demande, qui feraient
        # double emploi avec celles retenues.
        if set(dims) - {dimension} - set(filtres):
            continue
        totaux[modalite] = totaux.get(modalite, Decimal(0)) + o.valeur

    if not totaux:
        raise ErreurAnalyse(
            f"Aucune donnée ventilée par {dimension} pour "
            f"« {ind.libelle} » à {zone.nom} en {periode}.",
            motif="donnee_absente",
        )

    total = sum(totaux.values())
    lignes = [
        {
            "zone": _libelle(dimension, modalite),
            "code": modalite,
            "geojson_id": "",
            "valeur": valeur,
            "part": (valeur / total * 100) if total else Decimal(0),
        }
        for modalite, valeur in totaux.items()
    ]
    lignes.sort(key=_ordre(dimension))

    notes = [f"Répartition par {_nom_dimension(dimension)}, "
             f"sur un total de {int(total):,}".replace(",", " ")
             + f" {ind.unite}."]
    for cle in (ind.code, dimension):
        avert = _avertissement(cle)
        if avert:
            notes.append(avert)

    return AnalysisResult(
        lignes=lignes[:MAX_MODALITES],
        unite=ind.unite,
        sources=[source_de(ind)],
        chart_hint="bar",
        notes=notes,
        meta={"indicateur": ind.libelle, "zone": zone.nom,
              "periode": periode, "dimension": dimension,
              "total": total, "modalites": len(lignes),
              "filtres": filtres},
    )


# --- libellés --------------------------------------------------------------

NOMS_DIMENSION = {
    "sexe": "sexe",
    "age": "tranche d'âge",
    "milieu": "milieu de résidence",
    "quintile": "quintile de niveau de vie",
    "secteur": "secteur d'activité",
    "categorie_pro": "catégorie professionnelle",
    "type": "type",
}


def _nom_dimension(d):
    return NOMS_DIMENSION.get(d, d)


def _libelle_age(code):
    """
    Traduit un code de tranche d'âge SDMX.

        Y0T4    -> « 0 à 4 ans »
        Y_GE80  -> « 80 ans et plus »
        Y_LT15  -> « moins de 15 ans »
    """
    import re

    m = re.fullmatch(r"Y(\d+)T(\d+)", code)
    if m:
        return f"{m.group(1)} à {m.group(2)} ans"
    m = re.fullmatch(r"Y_GE(\d+)", code)
    if m:
        return f"{m.group(1)} ans et plus"
    m = re.fullmatch(r"Y_LT(\d+)", code)
    if m:
        return f"moins de {m.group(1)} ans"
    return code


# Les codes viennent des fichiers SDMX ; ces libellés ne servent qu'à
# l'affichage et ne sont jamais stockés.
_LIBELLES = {
    "sexe": {"H": "Hommes", "M": "Hommes", "F": "Femmes"},
    "milieu": {"U": "Urbain", "R": "Rural"},
    "quintile": {
        "PLUS_BAS": "Le plus pauvre", "SECOND": "Deuxième",
        "MOYEN": "Intermédiaire", "QUATRIEME": "Quatrième",
        "PLUS_ELEVE": "Le plus aisé",
    },
    "secteur": {
        "AGRI": "Agriculture", "INDUS": "Industrie",
        "COM_REP": "Commerce et réparation", "SERV": "Services",
    },
    "categorie_pro": {
        "SAL": "Salariés", "EMPL": "Employeurs",
        "IND_AGR": "Indépendants agricoles",
        "IND_NAGR": "Indépendants non agricoles",
        "APR_STA": "Apprentis et stagiaires",
    },
    "type": {
        "EAU_ROBINET_LOG": "Robinet dans le logement",
        "EAU_ROBINET_PUB": "Robinet public",
        "EAU_PUIT_POMPE": "Puits avec pompe",
        "EAU_PUIT_PROT": "Puits protégé",
        "EAU_PUIT_NON_PROT": "Puits non protégé",
    },
}


def _libelle(dimension, modalite):
    if dimension == "age":
        return _libelle_age(str(modalite))
    return _LIBELLES.get(dimension, {}).get(modalite, modalite)


def _avertissement(cle):
    return None

def _ordre(dimension):
    """
    Les tranches d'âge se lisent dans l'ordre croissant, les autres
    modalités par valeur décroissante.
    """
    if dimension == "age":
        def cle(ligne):
            code = str(ligne["code"])
            chiffres = "".join(c for c in code.split("T")[0] if c.isdigit())
            return int(chiffres) if chiffres else 999
        return cle
    return lambda ligne: -ligne["valeur"]

