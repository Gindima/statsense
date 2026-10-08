"""
data/seed/sdmx21.py

StatSense AI — Ingestion SDMX 2.1 (StructureSpecificData)

Format du catalogue standardisé de l'ANSD, différent de celui des comptes
nationaux trimestriels :

  - racine <StructureSpecificData> et non <CompactData>
  - AUCUN libellé d'indicateur dans le XML : l'indicateur est déterminé
    par le nom du fichier, d'où la table FICHIERS ci-dessous
  - dimensions variables d'un jeu à l'autre
  - noms d'attributs déformés par l'export : « RÉGIONS » devient
    « R_GIONS », « ÂGE » devient « GE ». Certains fichiers écrivent
    « R_GION » au singulier. On accepte donc plusieurs graphies.

Codes géographiques : « SN » pour le national, « SN-DK » pour une région.
Nos Zone portent des codes construits à partir des noms (SN-DAKAR), donc
la jointure passe par Zone.sdmx_code, renseigné par zones_sdmx, avec
Zone.geojson_id en repli.

Valeur « _T » : convention SDMX pour « toutes catégories confondues ».
Traduite en absence de dimension, pas en valeur littérale.


UN ATTRIBUT DE ZONE PARASITE, DANS LES NEUF FICHIERS

Chaque série porte trois attributs de zone. Deux concordent ; le
troisième, `REGIONID_RÉGIONS…`, contient un code de commune là où les
autres donnent une région :

    R_GIONS = SN-KE      REGIONID_RÉGIONS = SN-KE-KE-CU

Le taux de désaccord est de 12 à 13 % dans les neuf fichiers, toujours sur
cette seule colonne. `_code_geo` lit `R_GIONS` et ignore tout attribut
préfixé `ID_`, `REGIONID_` ou `F2_` : c'est délibéré, et c'est ce qui rend
le chargement correct malgré l'export.


DES TOTAUX QUI CONTREDISENT LEURS PROPRES COMPOSANTES

Dans population.xml, 24 cellules sur 458 portent un total « tous sexes »
incompatible avec les effectifs masculins et féminins de la même zone, la
même année et la même tranche d'âge :

    SN-DB · 2025    _T = 640 576        M + F = 2 208 278
    SN-FK · 2024    _T = 2 143 275      M + F =   932 652

Laquelle des deux séries croire ? Trois éléments tranchent, aucun
statistique :

  - au niveau national, _T vaut exactement M + F (19 075 959), donc les
    deux séries sont censées être commensurables ;
  - 434 cellules sur 458 vérifient déjà l'égalité ;
  - pour les 24 restantes, la somme M + F correspond à la zone attendue
    et le _T correspond à une autre zone du même fichier — le total est
    déplacé, les composantes ne le sont pas.

Règle appliquée : pour les indicateurs listés dans TOTAL_PAR_SOMME, le
total « tous sexes » est recalculé comme M + F lorsque les deux diffèrent
de plus de 0,5 %. Chaque substitution est comptée et nommée dans le
rapport de chargement — on ne remplace pas une donnée publiée en silence.

Cette règle ne s'applique QU'AUX EFFECTIFS. Un taux ou un indice ne
s'additionne pas entre modalités : un chômage national de 20,4 % avec
8 % chez les hommes et 23 % chez les femmes est une moyenne pondérée,
parfaitement cohérente, et la lui appliquer produirait 31 %.


DES TOTAUX QUI N'EXISTENT PAS DU TOUT

Problème symétrique, découvert sur eau_ameliore.xml :

    observations                        539
    lignes sans aucune ventilation        0
    périodes disponibles pour Kolda      []

Chaque série porte un type de source — robinet dans le logement, robinet
public, puits avec pompe, puits protégé, puits non protégé — et le fichier
n'écrit jamais `INDICATEURS = _T`. Il n'y a donc aucune ligne de total à
retirer, et aucune à lire : « Comment l'accès à l'eau a-t-il évolué à
Kolda ? » ne trouvait rien, alors que le catalogue annonce la série sur
2002-2023.

Le total est calculable, mais pas en sommant tout — et c'est l'erreur qui
a été commise puis corrigée ici, parce qu'elle est instructive.

Première version : sommer les cinq types, en s'appuyant sur une note
affirmant que « les cinq types sont exclusifs, leur somme donne le taux
d'accès global à une source améliorée ». Résultat obtenu pour Kolda :

    2002 : 98,0 %        2023 : 96,9 %

Invraisemblable, et dans le mauvais sens. La note était fausse. Les cinq
modalités sont bien exclusives et exhaustives, mais la cinquième — puits
NON protégé — n'est pas une source améliorée, c'en est la définition
inverse. Sommer les cinq donne donc la part des ménages dont la source
principale figure dans la liste, soit ≈ 100 %. Ce n'était pas un taux
d'accès, c'était presque la totalité des ménages.

Règle retenue : la table nomme les MODALITÉS à sommer, et non seulement la
dimension. Une dimension exclusive ne dit pas quelles modalités comptent,
et laisser ce choix implicite est précisément ce qui a permis l'erreur.
Pour l'eau, les quatre sources améliorées sont sommées et le puits non
protégé est écarté.

Trois précautions, parce qu'un chiffre construit engage davantage qu'un
chiffre lu :

  1. les modalités retenues sont écrites, une par une, et la somme ne
     porte que sur elles ;

  2. seuls les groupes portant TOUTES les modalités retenues sont sommés.
     Si une région-année n'en publie que trois sur quatre, la somme
     sous-estimerait le total, et un chiffre sous-estimé est pire qu'une
     absence. Ces groupes restent sans total, et leur nombre est rapporté ;

  3. les autres ventilations sont conservées : sommer les types à milieu
     constant donne le taux d'accès urbain, puis rural. Sommer ENTRE
     milieux n'aurait aucun sens, deux taux ne s'additionnant pas sans
     pondération.

Un dernier mot sur ce qui aurait dû alerter plus tôt : un taux construit
qui frôle 100 % sur toutes les zones et toutes les années ne mesure rien.
Le contrôle de vraisemblance appartient à la revue, pas au code — mais il
appartient à quelqu'un.
"""

import xml.etree.ElementTree as ET
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from catalog.models import Indicateur
from geography.models import Niveau, Zone
from observations.models import Observation

from utils import Compteur, to_decimal

# --- fichier -> code d'indicateur du catalogue -----------------------------
# Clé = nom du fichier sans extension, en minuscules, sans _ ni -.
#
# Volontairement absents :
#   pibprod / pibdepense / pibrevenu : fichiers identiques entre eux,
#     dimension COMPOSANTES codée (83 valeurs non documentées) et deux
#     bases de prix — charger sans les métadonnées mélangerait prix
#     courants et prix constants.
#   indicepauvrete : dimensions à valeurs vides, indicateurs A/B/C/D non
#     documentés, 3 points temporels seulement.

FICHIERS = {
    "population": "pop_region",
    "eclairage": "acces_electricite",
    "eauameliore": "acces_eau",
    "chomage": "taux_chomage_a",
    "emploi": "taux_emploi",
    "reemploi": "repartition_emploi",
    "natalite": "taux_natalite",
    "mortalite": "taux_mortalite",
    "bienetre": "indice_bienetre",
}

# Fichiers dont les valeurs sont des EFFECTIFS, donc pour lesquels le total
# doit égaler la somme de ses modalités. Clé = même forme que FICHIERS.
# N'ajouter ici que des dénombrements : jamais un taux, un indice ni un
# pourcentage.
TOTAL_PAR_SOMME = {"population"}

# Fichiers dont la source ne publie AUCUN total : il est construit par somme
# des modalités NOMMÉES ci-dessous.
#
# Nommer les modalités n'est pas une précaution de style. Les cinq types de
# source d'eau sont exclusifs et exhaustifs, mais le puits non protégé
# n'est pas une source améliorée : les sommer tous donnait 98 % à Kolda, ce
# qui mesurait la part des ménages ayant une source — n'importe laquelle —
# et non l'accès à l'eau améliorée.
#
# Avant d'ajouter une entrée ici, il faut donc pouvoir écrire quelles
# modalités composent la grandeur visée, et vérifier l'ordre de grandeur du
# résultat. Les tranches d'âge de population.xml ne qualifient pas : les
# 60-64 ans ne figurent dans aucune tranche publiée, donc aucune somme de
# tranches ne donne un total.
TOTAL_A_CONSTRUIRE = {
    "eauameliore": {
        "dimension": "type",
        # Les quatre sources améliorées, au sens de la définition
        # internationale : adduction dans le logement, borne-fontaine,
        # forage équipé d'une pompe, puits protégé.
        "retenues": ("EAU_ROBINET_LOG", "EAU_ROBINET_PUB",
                     "EAU_PUIT_POMPE", "EAU_PUIT_PROT"),
        # Écartée : puits non protégé. C'est la définition même d'une
        # source NON améliorée.
        "ecartees": ("EAU_PUIT_NON_PROT",),
    },
}

# Écart relatif au-delà duquel un total est jugé incompatible avec la somme
# de ses composantes. 0,5 % absorbe les arrondis de publication.
TOLERANCE_TOTAL = Decimal("0.005")
REGION_PAR_DEPARTEMENTS = {"population"}

# --- attributs de dimension -> clé stockée dans Observation.dims -----------
DIMENSIONS = {
    "SEXE": "sexe",
    "GE": "age",
    "ÂGE": "age",
    "AGE": "age",
    "GROUPE_D_GE": "age",
    "GROUPE_D-GE": "age",
    "GROUPE_D_ÂGE": "age",
    "INDICATEURS": "type",
    "FR_QUENCE_D_UTILISATION": "frequence_usage",
    "MILIEU_DE_R_SIDENCE": "milieu",
    "MILIEU_DE_RÉSIDENCE": "milieu",
    "QUINTILE": "quintile",
    "SECTEUR": "secteur",
    "CAT_GORIE_PROFESSIONNELLE": "categorie_pro",
    "CATÉGORIE_PROFESSIONNELLE": "categorie_pro",
}

# Attributs géographiques. R_GION au singulier existe aussi.
# Graphies rencontrées : souligné ET tiret, singulier ET pluriel.
GEO = ("R_GIONS", "R-GIONS", "R_GION", "R-GION",
       "RÉGIONS", "RÉGION", "REGIONS", "REGION",
       "REF_AREA", "INSPECTION_ACAD_MIQUE")

# Conventions de « toutes catégories » : _T (total), _Z (sans objet),
# « Ens » (ensemble) selon les fichiers.
TOTAUX = {"_T", "_Z", "Ens", "ENS", ""}

# Modalités de sexe telles qu'écrites dans les fichiers.
MASCULIN = ("M", "H")
FEMININ = ("F",)


def _local(tag):
    return tag.split("}")[-1]


def _code_geo(serie):
    """Extrait le code géographique, en ignorant les doublons ID_*."""
    for attr in GEO:
        v = serie.get(attr)
        if v:
            return v.strip()
    for k, v in serie.attrib.items():
        if not k.startswith(("ID_", "REGIONID_", "F2_")) \
                and str(v).upper().startswith("SN"):
            return str(v).strip()
    return None


def _dims(serie):
    """Ventilations réelles, hors totaux."""
    out = {}
    for attr, cle in DIMENSIONS.items():
        v = serie.get(attr)
        if v and v.strip() not in TOTAUX:
            out[cle] = v.strip()
    return out


def _sexe_brut(serie):
    """Modalité de sexe telle qu'écrite, y compris la valeur « total »."""
    for k in ("SEXE", "ID_SEXE"):
        v = serie.get(k)
        if v:
            return v.strip()
    return None


class ChargeurSDMX21:
    """Un fichier = un indicateur. Les séries ne diffèrent que par leurs
    ventilations et leur zone."""

    def __init__(self):
        self.indicateurs = {i.code: i for i in Indicateur.objects.all()}
        self.zones = self._index_zones()

    def _index_zones(self):
        """
        Index multi-clés code SDMX -> Zone, pour absorber les variantes de
        notation entre le SDMX (SN-DK) et le GeoJSON (SNDK, SN.DK, DK…).
        """
        idx = {}

        # Voie principale : sdmx_code, renseigné par zones_sdmx.
        # Couvre national, régions et départements.
        for z in Zone.objects.exclude(sdmx_code=""):
            idx[z.sdmx_code.upper()] = z

        # Repli : geojson_id, pour les régions rattachées avant que
        # sdmx_code n'existe.
        for z in Zone.objects.exclude(geojson_id=""):
            g = z.geojson_id.upper()
            for v in {g, g.replace("-", ""), g.replace(".", "")}:
                idx.setdefault(v, z)

        nat = Zone.objects.filter(niveau=Niveau.NATIONAL).first()
        if nat:
            idx.setdefault("SN", nat)
        return idx

    def _zone(self, code):
        if not code:
            return None
        c = code.upper().strip().replace("_", "-")
        for v in (c, c.replace("-", ""), c.replace(".", ""),
                  c.replace("SN-", "", 1)):
            z = self.zones.get(v)
            if z is not None:
                return z
        return None

    # -- correction des totaux ------------------------------------------

    @staticmethod
    def _corriger_totaux(mesures, compteur):
        """
        Remplace un total « tous sexes » par la somme des sexes lorsque les
        deux sont incompatibles.

        `mesures` : (zone, periode, cle_dims) -> (dims, valeur, sexe), où
        cle_dims est le tuple trié des ventilations. La comparaison ne
        porte que sur les cellules SANS autre ventilation que le sexe :
        comparer un total toutes tranches d'âge à une somme par sexe d'une
        seule tranche n'aurait pas de sens.
        """
        # Regroupe par (zone, periode) les trois cellules qui nous
        # intéressent : total, masculin, féminin, sans autre ventilation.
        groupes = defaultdict(dict)
        for (zone, periode, cle), (dims, valeur, sexe) in mesures.items():
            autres = {k for k in dims if k != "sexe"}
            if autres:
                continue
            if sexe is None:
                continue
            if sexe in TOTAUX:
                groupes[(zone, periode)]["T"] = (cle, valeur)
            elif sexe in MASCULIN:
                groupes[(zone, periode)]["M"] = (cle, valeur)
            elif sexe in FEMININ:
                groupes[(zone, periode)]["F"] = (cle, valeur)

        for (zone, periode), v in groupes.items():
            if not {"T", "M", "F"} <= set(v):
                continue
            cle_t, total = v["T"]
            somme = v["M"][1] + v["F"][1]
            if total <= 0:
                continue
            if abs(somme - total) / total <= TOLERANCE_TOTAL:
                continue

            dims, _, sexe = mesures[(zone, periode, cle_t)]
            mesures[(zone, periode, cle_t)] = (dims, somme, sexe)
            compteur.correction(
                f"{zone.nom} · {periode} — total publié {total:,.0f} "
                f"incompatible avec {v['M'][1]:,.0f} hommes + "
                f"{v['F'][1]:,.0f} femmes ; retenu {somme:,.0f}"
                .replace(",", " ")
            )

    @staticmethod
    def _aligner_regions(mesures, compteur):
        """
        Remplace la valeur d'une région par la somme de ses départements
        quand les deux divergent.

        Constaté dans population.xml : en 2023, 12 régions sur 14 portent
        la population d'une autre région (Thiès 245 147, celle de
        Kédougou). Hommes, femmes et total sont déplacés ensemble :
        _corriger_totaux ne peut pas le voir. Les départements sont justes
        (ceux de Thiès somment à 2 463 679, le chiffre du RGPH-5).

        Seulement si TOUS les départements de la région sont présents :
        une somme partielle sous-estimerait.
        """
        attendus = defaultdict(set)
        for zid, pid in (Zone.objects.filter(niveau=Niveau.DEPARTEMENT)
                         .values_list("id", "parent_id")):
            attendus[pid].add(zid)

        parts = defaultdict(dict)
        for (zone, periode, cle), (_d, valeur, _s) in mesures.items():
            if zone.niveau == Niveau.DEPARTEMENT and zone.parent_id:
                parts[(zone.parent_id, periode, cle)][zone.id] = valeur

        for (zone, periode, cle), (dims, valeur, sexe) in list(mesures.items()):
            if zone.niveau != Niveau.REGION:
                continue
            p = parts.get((zone.id, periode, cle))
            if not p or set(p) != attendus.get(zone.id, set()):
                continue
            somme = sum(p.values())
            if valeur > 0 and abs(somme - valeur) / valeur <= TOLERANCE_TOTAL:
                continue
            mesures[(zone, periode, cle)] = (dims, somme, sexe)
            compteur.correction(
                f"{zone.nom} · {periode} · {dict(cle) or 'total'} — publié "
                f"{valeur:,.0f}, somme des départements {somme:,.0f} ; "
                f"retenu {somme:,.0f}".replace(",", " "))

    @staticmethod
    def _construire_totaux(mesures, config, compteur):
        """
        Crée le total absent de la source, par somme des modalités NOMMÉES
        dans la configuration.

        `config` : {"dimension": …, "retenues": (…), "ecartees": (…)}.
        Seules les modalités `retenues` entrent dans la somme. Celles qui
        sont `ecartees` ne sont là que pour la documentation et le rapport
        de chargement : elles existent dans les données et sont
        délibérément laissées de côté.

        Les autres ventilations sont conservées : à milieu constant, la
        somme des types donne le taux d'accès de ce milieu. Sommer entre
        milieux n'aurait pas de sens, deux taux ne s'additionnant pas sans
        pondération.

        Seuls les groupes portant TOUTES les modalités retenues sont
        sommés. Un groupe partiel produirait un total sous-estimé, c'est-à-
        dire une réponse fausse donnée avec aplomb.
        """
        dimension = config["dimension"]
        retenues = set(config["retenues"])
        if len(retenues) < 2:
            return

        presentes = {dims[dimension]
                     for (_, _, _), (dims, _, _) in mesures.items()
                     if dimension in dims}
        absentes = retenues - presentes
        if absentes:
            # Une modalité déclarée mais introuvable signale un décalage
            # entre la table et le fichier : mieux vaut ne rien construire
            # que de sommer ce qui reste.
            compteur.erreur(
                0, f"modalités déclarées absentes du fichier pour "
                   f"« {dimension} » : {sorted(absentes)} — aucun total "
                   f"construit")
            return

        groupes = defaultdict(dict)
        for (zone, periode, _cle), (dims, valeur, _sexe) in mesures.items():
            modalite = dims.get(dimension)
            if modalite not in retenues:
                continue
            autres = {k: v for k, v in dims.items() if k != dimension}
            reference = (zone, periode, tuple(sorted(autres.items())))
            groupes[reference][modalite] = (valeur, autres)

        construits = incomplets = 0
        for reference, parts in groupes.items():
            if set(parts) != retenues:
                incomplets += 1
                continue
            if reference in mesures:
                continue            # la source publie déjà ce total
            autres = next(iter(parts.values()))[1]
            mesures[reference] = (
                dict(autres),
                sum(valeur for valeur, _ in parts.values()),
                None,
            )
            construits += 1

        if not construits and not incomplets:
            return

        detail = (f"total construit pour {construits} cellule(s), par somme "
                  f"de {len(retenues)} modalités de « {dimension} » : "
                  f"{', '.join(sorted(retenues))}")
        if config.get("ecartees"):
            detail += f" ; écartée(s) : {', '.join(config['ecartees'])}"
        if incomplets:
            detail += (f" ; {incomplets} groupe(s) incomplet(s) laissé(s) "
                       f"sans total")
        compteur.correction(detail)

    # -- point d'entrée --------------------------------------------------

    def charger(self, chemin, chargement):
        chemin = Path(chemin)
        compteur = Compteur(chemin.name)

        cle_fichier = chemin.stem.lower().replace("_", "").replace("-", "")
        code = FICHIERS.get(cle_fichier)
        if code is None:
            compteur.erreur(0, f"fichier non rattaché à un indicateur "
                               f"(clé « {cle_fichier} » absente de FICHIERS)")
            return compteur

        ind = self.indicateurs.get(code)
        if ind is None:
            compteur.erreur(0, f"indicateur « {code} » absent du catalogue")
            return compteur

        racine = ET.parse(chemin).getroot()
        zones_inconnues, dims_inconnues = set(), set()

        # (zone, periode, cle_dims) -> (dims, valeur, sexe_brut)
        mesures = {}

        for serie in racine.iter():
            if _local(serie.tag) != "Series":
                continue

            brut = _code_geo(serie)
            zone = self._zone(brut)
            if zone is None:
                zones_inconnues.add(brut)
                continue

            dims = _dims(serie)

            # Ventilation non déclarée au catalogue : on ignore la série
            # plutôt que de stocker une dimension que la validation
            # rejetterait ensuite à l'interrogation.
            inconnues = set(dims) - set(ind.dimensions)
            if inconnues:
                dims_inconnues |= inconnues
                continue

            sexe = _sexe_brut(serie)

            for obs in serie:
                if _local(obs.tag) != "Obs":
                    continue
                compteur.lignes += 1
                periode = obs.get("TIME_PERIOD")
                valeur = to_decimal(obs.get("OBS_VALUE"))
                if not periode or valeur is None:
                    continue
                cle = tuple(sorted(dims.items()))
                mesures[(zone, periode.strip(), cle)] = (dims, valeur, sexe)

        if cle_fichier in TOTAL_PAR_SOMME:
            self._corriger_totaux(mesures, compteur)

        if cle_fichier in REGION_PAR_DEPARTEMENTS:
            self._aligner_regions(mesures, compteur)

        config = TOTAL_A_CONSTRUIRE.get(cle_fichier)
        if config:
            self._construire_totaux(mesures, config, compteur)

        lot = [
            Observation(indicateur=ind, zone=zone, periode=periode,
                        dims=dims, valeur=valeur, chargement=chargement)
            for (zone, periode, _), (dims, valeur, _) in mesures.items()
        ]

        if lot:
            avant = Observation.objects.count()
            Observation.objects.bulk_create(lot, batch_size=1000,
                                            ignore_conflicts=True)
            compteur.observations = Observation.objects.count() - avant
            compteur.ignorees = len(lot) - compteur.observations

        if zones_inconnues:
            manquantes = sorted(x for x in zones_inconnues if x)
            compteur.erreur(0, f"zones sans code correspondant : "
                               f"{manquantes[:10]}")
        if dims_inconnues:
            compteur.erreur(0, f"dimensions non déclarées au catalogue pour "
                               f"{code} : {sorted(dims_inconnues)}")

        return compteur


def est_sdmx21(chemin):
    """Distingue ce format de l'ancien CompactData, sans tout parser."""
    try:
        tete = Path(chemin).read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return False
    return "StructureSpecificData" in tete


def fichiers_sdmx21(racine="data/raw/sdmx"):
    r = Path(racine)
    return sorted(f for f in list(r.glob("*.xml")) + list(r.glob("*.sdmx"))
                  if est_sdmx21(f))