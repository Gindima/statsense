"""
data/seed/catalogue_regional.py

StatSense AI — Extension du catalogue : indicateurs régionalisés annuels

Issus du catalogue standardisé de l'ANSD, format SDMX 2.1.

Ce que ces six indicateurs apportent : ce sont les PREMIERS à être à la
fois régionalisés ET temporels. Le recensement offrait la géographie sans
le temps, les comptes nationaux le temps sans la géographie. Ceux-ci
permettent enfin l'évolution par région et la carte animée.

À fusionner dans catalogue.py :

    from catalogue_regional import REGIONAL
    CATALOGUE = DEMOGRAPHIE + REGIONAL

Les valeurs de dimensions sont des codes SDMX conservés tels quels ; les
libellés lisibles sont dans LIBELLES_DIMENSIONS, à utiliser à l'affichage
et dans le prompt de narration.
"""

SOURCE_CATALOGUE_1M = {
    "catalogue_1m": {
        "nom": "ANSD — Catalogue de données standardisé (SDMX)",
        "url": "https://senegal.opendataforafrica.org",
        "plateforme": "Open Data for Africa / ANSD",
        "date_extraction": "2026-09-19",
        "note": "Format SDMX 2.1 StructureSpecificData. 14 régions + "
                "national, séries annuelles. Téléchargement via navigateur "
                "(protection anti-bot sur l'API).",
    },
}

_COMMUN = {
    "agregeable": False,          # taux, ratios et indices : jamais sommés
    "granularite_geo_min": "region",
    "frequence": "annuel",
    "comparaison_defaut": "n-1",
    "source": "catalogue_1m",
}

REGIONAL = [
    {
        **_COMMUN,
        "code": "taux_chomage_a",
        "libelle": "Taux de chômage (annuel, par région)",
        "synonymes": ["taux de chômage", "chômage par région", "chômage",
                      "sans emploi", "pourcentage de chômeurs",
                      "chômage des jeunes", "chômage des femmes"],
        "unite": "%",
        "dimensions": ["sexe", "age"],
    },
    {
        **_COMMUN,
        "code": "taux_emploi",
        "libelle": "Taux d'emploi",
        "synonymes": ["taux d'emploi", "emploi", "personnes qui travaillent",
                      "taux d'occupation", "population occupée"],
        "unite": "%",
        "dimensions": ["sexe", "age"],
    },
    {
        **_COMMUN,
        "code": "repartition_emploi",
        "libelle": "Répartition de l'emploi par secteur et catégorie",
        "synonymes": ["répartition de l'emploi", "emploi par secteur",
                      "secteurs d'activité", "dans quoi travaillent les gens",
                      "catégorie professionnelle", "salariés"],
        "unite": "%",
        "dimensions": ["sexe", "secteur", "categorie_pro"],
    },
    {
        **_COMMUN,
        "code": "taux_natalite",
        "libelle": "Taux brut de natalité",
        "synonymes": ["natalité", "taux de natalité", "naissances",
                      "combien de naissances", "fécondité"],
        "unite": "‰",
        "dimensions": ["milieu"],
    },
    {
        **_COMMUN,
        "code": "taux_mortalite",
        "libelle": "Taux brut de mortalité",
        "synonymes": ["mortalité", "taux de mortalité", "décès",
                      "combien de décès"],
        "unite": "‰",
        "dimensions": ["sexe", "milieu"],
    },
    {
        **_COMMUN,
        "code": "indice_bienetre",
        "libelle": "Indice de bien-être",
        "synonymes": ["bien-être", "indice de bien-être", "niveau de vie",
                      "conditions de vie", "quintile de richesse"],
        "unite": "indice",
        "dimensions": ["milieu", "quintile"],
    },
]


# --- libellés des codes de dimension --------------------------------------
# Les fichiers SDMX ne portent que des codes. Ces libellés servent à
# l'affichage et à la narration ; ils ne sont pas stockés en base.
LIBELLES_DIMENSIONS = {
    "sexe": {
        "F": "Femmes",
        "M": "Hommes",
    },
    "age": {
        "Y15T24": "15 à 24 ans",
        "Y25T34": "25 à 34 ans",
        "Y35T59": "35 à 59 ans",
        "Y_GE65": "65 ans et plus",
    },
    "milieu": {
        "U": "Urbain",
        "R": "Rural",
    },
    "quintile": {
        "PLUS_BAS": "Quintile le plus bas",
        "SECOND": "Deuxième quintile",
        "MOYEN": "Quintile moyen",
        "QUATRIEME": "Quatrième quintile",
        "PLUS_ELEVE": "Quintile le plus élevé",
    },
    "secteur": {
        "AGRI": "Agriculture",
        "INDUS": "Industrie",
        "COM_REP": "Commerce et réparation",
        "SERV": "Services",
    },
    "categorie_pro": {
        "SAL": "Salariés",
        "EMPL": "Employeurs",
        "IND_AGR": "Indépendants agricoles",
        "IND_NAGR": "Indépendants non agricoles",
        "APR_STA": "Apprentis et stagiaires",
    },
}


def libelle(dimension, code):
    """Traduit un code de dimension en libellé lisible, ou le rend tel quel."""
    return LIBELLES_DIMENSIONS.get(dimension, {}).get(code, code)


# --- note sur la tranche d'âge manquante ----------------------------------
# Les tranches couvrent 15-24, 25-34, 35-59 et 65+. Les 60-64 ans ne sont
# dans aucune tranche : les parts ne totalisent donc pas 100 %. À signaler
# dans les notes méthodologiques de toute analyse ventilée par âge.
AVERTISSEMENTS = {
    "age": "Les tranches d'âge publiées ne couvrent pas les 60-64 ans ; "
           "les ventilations par âge ne totalisent pas 100 %.",
    "indice_bienetre": "Série irrégulière : 11 points entre 1997 et 2023.",
    "taux_natalite": "Série irrégulière : 17 points entre 1992 et 2025.",
}

# --- indicateurs supplémentaires -------------------------------------------

REGIONAL += [
    {
        **_COMMUN,
        "code": "pop_region",
        # « Projetée » plutôt que « par région et département » : le niveau
        # géographique est déjà porté par granularite_geo_min, alors que la
        # nature de la série — une projection, non un dénombrement — n'est
        # lisible nulle part ailleurs. C'est elle qui distingue cet
        # indicateur de pop_totale aux yeux du modèle.
        "libelle": "Population projetée (projections annuelles)",
        "synonymes": ["pyramide des âges", "structure par âge",
                      "population par âge", "population par tranche d'âge",
                      "évolution de la population",
                      "croissance démographique",
                      "population par département",
                      "population projetée", "projections de population"],
        "unite": "personnes",
        "dimensions": ["sexe", "age"],
        "agregeable": True,             # effectif : sommable entre zones
        "granularite_geo_min": "departement",
    },
    {
        **_COMMUN,
        "code": "acces_electricite",
        "libelle": "Ménages ayant l'électricité comme source d'éclairage",
        "synonymes": ["électricité", "accès à l'électricité", "éclairage",
                      "électrification", "ménages électrifiés",
                      "qui a l'électricité"],
        "unite": "%",
        "dimensions": ["milieu"],
    },
    {
        **_COMMUN,
        "code": "acces_eau",
        "libelle": "Accès à une source d'eau améliorée",
        "synonymes": ["eau", "accès à l'eau", "eau potable",
                      "eau améliorée", "robinet", "puits",
                      "approvisionnement en eau"],
        "unite": "%",
        "dimensions": ["milieu", "type"],
    },
]

LIBELLES_DIMENSIONS["type"] = {
    "EAU_ROBINET_LOG": "Robinet dans le logement",
    "EAU_ROBINET_PUB": "Robinet public",
    "EAU_PUIT_POMPE": "Puits avec pompe",
    "EAU_PUIT_PROT": "Puits protégé",
    "EAU_PUIT_NON_PROT": "Puits non protégé",
}

# Tranches d'âge quinquennales de population.xml, distinctes des tranches
# larges utilisées par les fichiers emploi et chômage.
LIBELLES_DIMENSIONS["age"].update({
    f"Y{d}T{d + 4}": f"{d} à {d + 4} ans" for d in range(0, 80, 5)
})
LIBELLES_DIMENSIONS["age"]["Y_GE80"] = "80 ans et plus"

# Cette note disait, à tort, que la somme des CINQ types donnait le taux
# d'accès à une source améliorée. Elle a conduit à construire une série où
# Kolda affichait 98 % en 2002 : la somme des cinq mesure la part des
# ménages ayant une source quelconque, soit la quasi-totalité.
#
# Le puits non protégé est, par définition, une source NON améliorée. Le
# taux d'accès est donc la somme des quatre autres, et c'est ce que
# construit sdmx21.TOTAL_A_CONSTRUIRE.
AVERTISSEMENTS["acces_eau"] = (
    "Les cinq types de source sont exclusifs et couvrent l'ensemble des "
    "ménages. Le taux d'accès affiché sans ventilation est la somme des "
    "quatre sources améliorées — robinet dans le logement, robinet public, "
    "puits avec pompe, puits protégé — calculée au chargement ; le puits "
    "non protégé en est exclu, n'étant pas une source améliorée."
)