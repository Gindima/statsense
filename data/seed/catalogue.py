"""
data/seed/catalogue.py

StatSense AI — Catalogue d'indicateurs
======================================

Source unique de vérité pour :
  - le seed de la table `catalog.Indicateur`
  - le prompt d'extraction de Qwen (métadonnées uniquement)
  - la section « Liste des jeux de données à utiliser » du dossier ANSD

Chaque indicateur est décrit par des MÉTADONNÉES uniquement.
Aucune valeur chiffrée n'apparaît ici : les chiffres vivent dans
`observations.Observation` et ne sont jamais exposés au modèle.

Champs
------
code                 identifiant technique stable, jamais affiché
libelle              nom lisible affiché à l'utilisateur
synonymes            formulations attendues des utilisateurs — DÉCISIF pour le taux
                     de compréhension. À enrichir en continu via le Django admin.
unite                unité d'affichage
dimensions           ventilations autorisées ; toute autre est rejetée à la validation
agregeable           True = sommable entre zones (effectif) / False = taux, moyenne
granularite_geo_min  niveau géographique le plus fin disponible
frequence            ponctuel | annuel | trimestriel
comparaison_defaut   n-1 (annuel) | t-4 (trimestriel, glissement annuel)
prix_base            renseigné uniquement pour les agrégats monétaires réels
derive_de            si l'indicateur est calculé, formule sur d'autres codes
source               clé vers SOURCES


DEUX SÉRIES DE POPULATION, DEUX LIBELLÉS QUI LES SÉPARENT

`pop_totale` et `pop_region` mesurent tous deux une population, et c'est
légitime : l'un dénombre (recensement 2023, jusqu'au quartier), l'autre
projette (séries annuelles 2016-2025, jusqu'au département). Leurs valeurs
diffèrent donc normalement — 4 004 425 contre 3 372 557 pour Dakar.

Tant qu'ils s'appelaient tous deux « Population… », le modèle n'avait
aucun moyen de choisir : « la population de Dakar en 2020 » tombait sur le
recensement et se faisait refuser pour période non couverte, alors que la
série projetée couvre 2020.

Les libellés portent maintenant la distinction, parce que c'est la seule
information que le modèle lit et qu'aucune règle de code ne peut
l'inventer : choisir entre dénombrer et projeter relève de l'intention de
la question, pas d'une forme fermée.
"""

# ---------------------------------------------------------------------------
# SOURCES
# ---------------------------------------------------------------------------
from catalogue_regional import REGIONAL, SOURCE_CATALOGUE_1M


SOURCES = {
    "rgph2023": {
        "nom": "ANSD — Recensement Général de la Population et de l'Habitat (RGPH-5), 2023",
        "url": "https://www.ansd.sn/recensement/rgph-5-2023",
        "plateforme": "Site officiel ANSD",
        "date_extraction": "2026-07-25",
        "note": "14 fichiers CSV, un par région, niveau quartier/village/hameau.",
    },
    "cn_pib": {
        "nom": "ANSD — Comptes nationaux trimestriels, PIB",
        "url": "https://www.stat.sn",
        "plateforme": "Stats Sénégal (SDMX)",
        "date_extraction": "2026-07-25",
        "note": "28 séries trimestrielles 2008-Q1 → 2026-Q1, prix constants 2014, "
                "milliards FCFA. UNIT_MULT à ignorer.",
    },
    "emploi": {
        "nom": "ANSD — Enquête nationale sur l'emploi au Sénégal (ENES)",
        "url": "https://www.stat.sn",
        "plateforme": "Stats Sénégal (SDMX)",
        "date_extraction": "2026-07-25",
        "note": "9 séries, trimestrielles 2016-Q2 → 2026-Q1 + point annuel 2015.",
    },
    "geo_anat": {
        "nom": "Limites administratives du Sénégal — 14 régions",
        "url": "https://simplemaps.com/gis/country/sn",
        "plateforme": "Simplemaps (CC BY 4.0)",
        "date_extraction": "2026-07-26",
        "note": "GeoJSON servi en statique au frontend. Aucune géométrie en base.",
    },
}

# ---------------------------------------------------------------------------
# DOMAINE 1 — DÉMOGRAPHIE (RGPH 2023)
# Granularité : quartier. Aucune dimension temporelle.
# ---------------------------------------------------------------------------

DEMOGRAPHIE = [
    {
        "code": "pop_totale",
        # Le millésime est dans le libellé : c'est ce qui distingue cette
        # série du dénombrement de celle des projections annuelles.
        "libelle": "Population recensée (RGPH-5, 2023)",
        "synonymes": ["population", "habitants", "nombre d'habitants",
                      "combien de gens", "combien de personnes",
                      "démographie", "peuplement", "peuplée", "peuplées",
                      "peuplé", "résidents", "recensement",
                      "population recensée", "population féminine",
                      "population masculine"],
        "unite": "personnes",
        "dimensions": ["sexe"],
        "agregeable": True,
        "granularite_geo_min": "quartier",
        "frequence": "ponctuel",
        "comparaison_defaut": None,
        "source": "rgph2023",
    },
    {
        "code": "menages",
        "libelle": "Nombre de ménages",
        "synonymes": ["ménages", "menages", "foyers", "nombre de foyers",
                      "combien de ménages"],
        "unite": "ménages",
        "dimensions": [],
        "agregeable": True,
        "granularite_geo_min": "quartier",
        "frequence": "ponctuel",
        "comparaison_defaut": None,
        "source": "rgph2023",
    },
    {
        "code": "concessions",
        "libelle": "Nombre de concessions",
        "synonymes": ["concessions", "parcelles", "parcelles bâties", "habitations"],
        "unite": "concessions",
        "dimensions": [],
        "agregeable": True,
        "granularite_geo_min": "quartier",
        "frequence": "ponctuel",
        "comparaison_defaut": None,
        "source": "rgph2023",
    },
    {
        "code": "taille_menage",
        "libelle": "Taille moyenne des ménages",
        "synonymes": ["taille des ménages", "taille moyenne des ménages",
                      "personnes par ménage", "combien de personnes par foyer",
                      "taille des foyers", "grands ménages",
                      "ménages les plus grands", "ménages les plus petits",
                      "ménages nombreux"],
        "unite": "personnes par ménage",
        "dimensions": [],
        "agregeable": False,          # moyenne : jamais sommer entre zones
        "granularite_geo_min": "quartier",
        "frequence": "ponctuel",
        "comparaison_defaut": None,
        "derive_de": "pop_totale / menages",
        "source": "rgph2023",
    },
    {
        "code": "rapport_masculinite",
        "libelle": "Rapport de masculinité",
        "synonymes": ["rapport de masculinité", "ratio hommes femmes",
                      "proportion d'hommes", "équilibre hommes femmes",
                      "y a-t-il plus d'hommes ou de femmes"],
        "unite": "hommes pour 100 femmes",
        "dimensions": [],
        "agregeable": False,
        "granularite_geo_min": "quartier",
        "frequence": "ponctuel",
        "comparaison_defaut": None,
        "derive_de": "pop_totale[sexe=H] / pop_totale[sexe=F] * 100",
        "source": "rgph2023",
    },
    {
        "code": "menages_par_concession",
        "libelle": "Ménages par concession",
        "synonymes": ["ménages par concession", "densité d'occupation",
                      "combien de ménages par parcelle", "promiscuité"],
        "unite": "ménages par concession",
        "dimensions": [],
        "agregeable": False,
        "granularite_geo_min": "quartier",
        "frequence": "ponctuel",
        "comparaison_defaut": None,
        "derive_de": "menages / concessions",
        "source": "rgph2023",
    },
    {
        "code": "part_population",
        "libelle": "Poids démographique",
        "synonymes": ["part de la population", "poids démographique", "pourcentage",
                      "quelle proportion", "part dans la population totale"],
        "unite": "%",
        "dimensions": ["sexe"],
        "agregeable": False,
        "granularite_geo_min": "quartier",
        "frequence": "ponctuel",
        "comparaison_defaut": None,
        "derive_de": "pop_totale[zone] / pop_totale[parent] * 100",
        "source": "rgph2023",
    },
]

# ---------------------------------------------------------------------------
# DOMAINE 2 — COMPTES NATIONAUX (SDMX, trimestriel)
# Granularité : national uniquement. 73 trimestres.
# ATTENTION : forte saisonnalité → comparaison_defaut = "t-4" partout.
# ---------------------------------------------------------------------------

_PIB_COMMUN = {
    "unite": "milliards FCFA",
    "dimensions": [],
    "agregeable": True,
    "granularite_geo_min": "national",
    "frequence": "trimestriel",
    "comparaison_defaut": "t-4",     # glissement annuel : jamais T vs T-1
    "prix_base": "constants 2014",
    "source": "cn_pib",
}

def _pib(code, libelle, synonymes, niveau, parent=None):
    """niveau : total | secteur | branche — sert à la méthode `repartition`."""
    return {**_PIB_COMMUN, "code": code, "libelle": libelle,
            "synonymes": synonymes, "niveau_sectoriel": niveau,
            "secteur_parent": parent}

COMPTES_NATIONAUX = [
    _pib("pib_total", "Produit intérieur brut",
         ["PIB", "produit intérieur brut", "richesse produite", "économie",
          "croissance économique", "taille de l'économie"], "total"),

    # --- Secteurs ---
    _pib("va_primaire", "Valeur ajoutée du secteur primaire",
         ["secteur primaire", "primaire", "agriculture élevage pêche"],
         "secteur", None),
    _pib("va_secondaire", "Valeur ajoutée du secteur secondaire",
         ["secteur secondaire", "secondaire", "industrie"], "secteur", None),
    _pib("va_tertiaire", "Valeur ajoutée du secteur tertiaire",
         ["secteur tertiaire", "tertiaire", "services"], "secteur", None),

    # --- Branches du primaire ---
    _pib("va_agriculture", "Agriculture et activités annexes",
         ["agriculture", "cultures", "production agricole"], "branche", "va_primaire"),
    _pib("va_elevage", "Élevage et chasse",
         ["élevage", "bétail", "chasse"], "branche", "va_primaire"),
    _pib("va_sylviculture", "Sylviculture et exploitation forestière",
         ["sylviculture", "forêt", "exploitation forestière", "bois"],
         "branche", "va_primaire"),
    _pib("va_peche", "Pêche, aquaculture et pisciculture",
         ["pêche", "aquaculture", "pisciculture", "produits halieutiques"],
         "branche", "va_primaire"),

    # --- Branches du secondaire ---
    _pib("va_extractives", "Activités extractives",
         ["activités extractives", "mines", "extraction minière", "pétrole"],
         "branche", "va_secondaire"),
    _pib("va_agroalim", "Fabrication de produits agro-alimentaires",
         ["agro-alimentaire", "agroalimentaire", "industrie alimentaire"],
         "branche", "va_secondaire"),
    _pib("va_raffinage", "Raffinage du pétrole et cokéfaction",
         ["raffinage", "pétrole raffiné", "cokéfaction"], "branche", "va_secondaire"),
    _pib("va_chimie", "Fabrication de produits chimiques de base",
         ["chimie", "produits chimiques", "industrie chimique"],
         "branche", "va_secondaire"),
    _pib("va_ciment", "Fabrication de ciment et matériaux de construction",
         ["ciment", "matériaux de construction", "BTP matériaux"],
         "branche", "va_secondaire"),
    _pib("va_manufacturier", "Fabrication d'autres produits manufacturiers",
         ["manufacturier", "industrie manufacturière", "autres industries"],
         "branche", "va_secondaire"),
    _pib("va_electricite", "Production et distribution d'électricité et de gaz",
         ["électricité", "energie", "gaz", "production électrique"],
         "branche", "va_secondaire"),
    _pib("va_eau", "Production et distribution d'eau, assainissement",
         ["eau", "assainissement", "traitement des déchets", "distribution d'eau"],
         "branche", "va_secondaire"),
    _pib("va_construction", "Construction",
         ["construction", "bâtiment", "BTP", "travaux publics"],
         "branche", "va_secondaire"),

    # --- Branches du tertiaire ---
    _pib("va_commerce", "Commerce",
         ["commerce", "négoce", "distribution"], "branche", "va_tertiaire"),
    _pib("va_transports", "Transports",
         ["transport", "transports", "logistique"], "branche", "va_tertiaire"),
    _pib("va_hebergement", "Hébergement et restauration",
         ["hôtellerie", "restauration", "tourisme", "hébergement"],
         "branche", "va_tertiaire"),
    _pib("va_information", "Information et communication",
         ["télécoms", "télécommunications", "information et communication",
          "numérique", "TIC"], "branche", "va_tertiaire"),
    _pib("va_finance", "Activités financières et d'assurance",
         ["finance", "banques", "assurance", "secteur financier"],
         "branche", "va_tertiaire"),
    _pib("va_immobilier", "Activités immobilières",
         ["immobilier", "logement", "activités immobilières"],
         "branche", "va_tertiaire"),
    _pib("va_services_entr", "Services aux entreprises",
         ["services aux entreprises", "conseil", "services professionnels"],
         "branche", "va_tertiaire"),
    _pib("va_admin", "Administration publique, enseignement et santé",
         ["administration publique", "enseignement", "santé", "services publics",
          "fonction publique"], "branche", "va_tertiaire"),
    _pib("va_domestique", "Activités domestiques",
         ["activités domestiques", "travail domestique"], "branche", "va_tertiaire"),
    _pib("va_autres_services", "Autres activités de services",
         ["autres services"], "branche", "va_tertiaire"),

    _pib("taxes_nettes", "Taxes nettes sur les produits",
         ["taxes", "taxes nettes", "impôts sur les produits", "TVA"], "total"),
]

# ---------------------------------------------------------------------------
# DOMAINE 3 — MARCHÉ DU TRAVAIL (SDMX)
# Trimestriel 2016-Q2 → 2026-Q1, + un point annuel 2015. National uniquement.
# Saisonnalité marquée sur le chômage → t-4 obligatoire.
# ---------------------------------------------------------------------------

MARCHE_TRAVAIL = [
    {
        "code": "pop_active",
        "libelle": "Population active",
        "synonymes": ["population active", "actifs", "force de travail",
                      "main d'oeuvre", "personnes actives"],
        "unite": "personnes",
        "dimensions": [],
        "agregeable": True,
        "granularite_geo_min": "national",
        "frequence": "trimestriel",
        "comparaison_defaut": "t-4",
        "source": "emploi",
    },
    {
        "code": "pop_occupee",
        "libelle": "Population occupée",
        "synonymes": ["population occupée", "personnes en emploi", "actifs occupés",
                      "combien de gens travaillent", "emploi"],
        "unite": "personnes",
        "dimensions": [],
        "agregeable": True,
        "granularite_geo_min": "national",
        "frequence": "trimestriel",
        "comparaison_defaut": "t-4",
        "source": "emploi",
    },
    {
        "code": "pop_chomage",
        "libelle": "Population au chômage",
        "synonymes": ["chômeurs", "population au chômage", "nombre de chômeurs",
                      "sans emploi", "demandeurs d'emploi"],
        "unite": "personnes",
        "dimensions": [],
        "agregeable": True,
        "granularite_geo_min": "national",
        "frequence": "trimestriel",
        "comparaison_defaut": "t-4",
        "source": "emploi",
    },
    {
        "code": "taux_chomage",
        "libelle": "Taux de chômage",
        "synonymes": ["taux de chômage", "chômage", "pourcentage de chômeurs",
                      "combien de chômage"],
        "unite": "%",
        "dimensions": [],
        "agregeable": False,          # ne jamais sommer ni moyenner sans pondération
        "granularite_geo_min": "national",
        "frequence": "trimestriel",
        "comparaison_defaut": "t-4",
        "source": "emploi",
    },
    {
        "code": "salaire_moyen",
        "libelle": "Salaire moyen mensuel",
        "synonymes": ["salaire moyen", "salaire", "rémunération moyenne",
                      "combien gagne un salarié", "revenu salarial"],
        "unite": "FCFA par mois",
        "dimensions": [],
        "agregeable": False,
        "granularite_geo_min": "national",
        "frequence": "trimestriel",
        "comparaison_defaut": "t-4",
        "source": "emploi",
    },
]

# ---------------------------------------------------------------------------
# ASSEMBLAGE
# ---------------------------------------------------------------------------
SOURCES.update(SOURCE_CATALOGUE_1M)

# COMPTES_NATIONAUX et MARCHE_TRAVAIL sont décrits ci-dessus mais ne sont
# pas assemblés : les fichiers SDMX existent, leur chargeur n'est pas
# écrit, et aucune observation ne les alimente.
#
# Un indicateur présent au catalogue sans observation serait pire que son
# absence : la question « quel est le PIB du Sénégal ? » produirait un
# refus pour série absente, en laissant croire que la donnée existe
# quelque part, au lieu du refus exact — l'indicateur n'est pas au
# catalogue. Ils y entreront le jour où leur chargeur sera écrit.
CATALOGUE = DEMOGRAPHIE + REGIONAL

# ---------------------------------------------------------------------------
# CONTRÔLES DE COHÉRENCE — à exécuter avant tout seed
# ---------------------------------------------------------------------------

def controler(catalogue=CATALOGUE):
    """Échoue bruyamment plutôt que de charger un catalogue incohérent."""
    erreurs = []

    codes = [i["code"] for i in catalogue]
    doublons = {c for c in codes if codes.count(c) > 1}
    if doublons:
        erreurs.append(f"codes dupliqués : {doublons}")

    for i in catalogue:
        if i["source"] not in SOURCES:
            erreurs.append(f"{i['code']} : source inconnue « {i['source']} »")

        if not i["synonymes"]:
            erreurs.append(f"{i['code']} : aucun synonyme — sera introuvable")

        if i["frequence"] == "trimestriel" and i.get("comparaison_defaut") != "t-4":
            erreurs.append(f"{i['code']} : série trimestrielle sans glissement annuel")

        if i["unite"] == "%" and i["agregeable"]:
            erreurs.append(f"{i['code']} : un pourcentage ne peut pas être agrégeable")

        parent = i.get("secteur_parent")
        if parent and parent not in codes:
            erreurs.append(f"{i['code']} : secteur parent « {parent} » absent")

    # collision de synonymes entre indicateurs différents
    vus = {}
    for i in catalogue:
        for s in i["synonymes"]:
            cle = s.lower().strip()
            if cle in vus:
                erreurs.append(
                    f"synonyme ambigu « {s} » : {vus[cle]} et {i['code']}")
            vus[cle] = i["code"]

    if erreurs:
        raise ValueError("Catalogue incohérent :\n  - " + "\n  - ".join(erreurs))

    return {
        "indicateurs": len(catalogue),
        "sources": len(SOURCES),
        "synonymes": sum(len(i["synonymes"]) for i in catalogue),
    }


if __name__ == "__main__":
    print(controler())