"""
StatSense AI — Ingestion des fichiers SDMX (PIB, marché du travail)

Trois pièges corrigés ici, tous constatés sur les fichiers réels :

1. ARTEFACT DE NAVIGATEUR
   Les fichiers commencent par « This XML file does not appear to have
   any style information... ». C'est du texte injecté par l'affichage du
   navigateur, pas du contenu. Un parseur XML strict échoue dessus.

2. UNIT_MULT TROMPEUR
   L'attribut annonce un facteur 10^9, mais le libellé indique déjà
   « en milliards de FCFA ». Vérification : le PIB 2026-Q1 vaut 4 395,
   soit ~17 600 milliards par an — ordre de grandeur correct pour le
   Sénégal. UNIT_MULT est donc IGNORÉ.

3. PRIX CONSTANTS
   BASE_PER=2014 : il s'agit du PIB réel, pas nominal. Porté par
   Indicateur.prix_base et affiché à l'utilisateur.

Toutes ces séries sont nationales (REF_AREA=SN) : aucune ventilation
géographique n'est possible, d'où granularite_geo_min = "national".
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from catalog.models import Indicateur
from geography.models import Niveau, Zone
from observations.models import Observation

from utils import Compteur, to_decimal

CODE_NATIONAL = "SN"

# Libellé SDMX (normalisé) -> code du catalogue.
# Le rapprochement se fait sur NOMFR_INDICATOR, seul identifiant lisible
# commun aux deux fichiers.
CORRESPONDANCES = {
    # --- comptes nationaux ---
    # Les libellés réels comportent « (VA) », des parenthèses d'unité et
    # une faute de frappe (« RAFINAGE ») : les motifs ci-dessous sont
    # calibrés sur les fichiers effectivement téléchargés.
    "produit interieur brut": "pib_total",
    "secteur primaire": "va_primaire",
    "secteur secondaire": "va_secondaire",
    "secteur tertiaire": "va_tertiaire",
    "agriculture": "va_agriculture",
    "elevage": "va_elevage",
    "sylviculture": "va_sylviculture",
    "peche": "va_peche",
    "activites extractives": "va_extractives",
    "agro-alimentaire": "va_agroalim",
    "raffinage": "va_raffinage",
    "rafinage": "va_raffinage",          # faute de frappe dans la source
    "produits chimiques": "va_chimie",
    "ciment": "va_ciment",
    "manufacturier": "va_manufacturier",
    "electricite": "va_electricite",
    "eau": "va_eau",
    "construction": "va_construction",
    "commerce": "va_commerce",
    "transports": "va_transports",
    "hebergement": "va_hebergement",
    "information et communication": "va_information",
    "financieres": "va_finance",
    "immobilieres": "va_immobilier",
    "services aux entreprises": "va_services_entr",
    "administration publique": "va_admin",
    "domestiques": "va_domestique",
    "autres activites de services": "va_autres_services",
    "taxes nettes": "taxes_nettes",
    # --- marché du travail ---
    "population active": "pop_active",
    "population occupee": "pop_occupee",
    "population au chomage": "pop_chomage",
    "taux de chomage": "taux_chomage",
    "salaire moyen": "salaire_moyen",
}


def _nettoyer(chemin):
    """Retire l'artefact de navigateur avant la déclaration XML."""
    texte = Path(chemin).read_text(encoding="utf-8", errors="replace")

    tete = texte[:600].lower()
    if "<!doctype html" in tete or "just a moment" in tete:
        raise ValueError(
            f"{Path(chemin).name} : page HTML et non XML — téléchargement "
            f"bloqué par une protection anti-bot. Enregistrez le fichier "
            f"depuis le navigateur."
        )

    debut = texte.find("<?xml")
    if debut == -1:
        debut = texte.find("<")
    return texte[debut:]


def _cle(libelle):
    """Normalise un libellé SDMX pour le rapprochement."""
    s = libelle.lower()
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("à", "a").replace("ô", "o").replace("î", "i")
           .replace("ç", "c").replace("û", "u"))
    return re.sub(r"\s+", " ", s).strip()


def _resoudre(libelle):
    """Rapproche un libellé SDMX d'un code du catalogue, ou None."""
    k = _cle(libelle)
    if k in CORRESPONDANCES:
        return CORRESPONDANCES[k]
    for motif, code in CORRESPONDANCES.items():
        if motif in k:
            return code
    return None


def _zone_nationale():
    z, _ = Zone.objects.get_or_create(
        code="SN",
        defaults={"nom": "SENEGAL", "niveau": Niveau.NATIONAL,
                  "parent": None, "geojson_id": CODE_NATIONAL},
    )
    return z


class ChargeurSDMX:

    def __init__(self):
        self.indicateurs = {i.code: i for i in Indicateur.objects.all()}
        self.zone = _zone_nationale()

    def charger(self, chemin, chargement):
        chemin = Path(chemin)
        compteur = Compteur(chemin.name)
        racine = ET.fromstring(_nettoyer(chemin))
        lot = []
        inconnus = set()

        for serie in racine.iter():
            if not serie.tag.endswith("Series"):
                continue

            libelle = serie.get("NOMFR_INDICATOR") or ""
            code = _resoudre(libelle)
            if code is None:
                inconnus.add(libelle[:60])
                continue

            ind = self.indicateurs.get(code)
            if ind is None:
                inconnus.add(f"{libelle[:40]} -> {code} absent du catalogue")
                continue

            # Le fichier emploi contient, pour un même indicateur, une série
            # trimestrielle (40 points) ET une série annuelle orpheline
            # (un seul point, 2015). Les charger toutes deux mélangerait
            # deux fréquences dans une même série et fausserait la méthode
            # `evolution`. Le catalogue fait foi.
            freq = serie.get("FREQ")
            attendue = {"trimestriel": "Q", "annuel": "A"}.get(ind.frequence)
            if attendue and freq and freq != attendue:
                compteur.erreur(
                    0, f"série {freq} ignorée pour {code} "
                       f"(catalogue : {ind.frequence})")
                continue

            for obs in serie:
                if not obs.tag.endswith("Obs"):
                    continue
                compteur.lignes += 1
                periode = obs.get("TIME_PERIOD")
                valeur = to_decimal(obs.get("OBS_VALUE"))
                if not periode or valeur is None:
                    continue
                # UNIT_MULT volontairement ignoré : cf. en-tête du module.
                lot.append(Observation(
                    indicateur=ind, zone=self.zone, periode=periode,
                    dims={}, valeur=valeur, chargement=chargement,
                ))

        if lot:
            avant = Observation.objects.count()
            Observation.objects.bulk_create(lot, batch_size=1000,
                                            ignore_conflicts=True)
            compteur.observations = Observation.objects.count() - avant
            compteur.ignorees = len(lot) - compteur.observations

        for x in sorted(inconnus):
            compteur.erreur(0, f"série non rapprochée : {x}")

        return compteur


def fichiers_sdmx(racine="data/raw/sdmx"):
    r = Path(racine)
    return sorted(list(r.glob("*.xml")) + list(r.glob("*.sdmx")))