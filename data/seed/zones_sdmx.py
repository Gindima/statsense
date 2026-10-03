"""
data/seed/zones_sdmx.py

StatSense AI — Correspondance des codes géographiques SDMX

Les fichiers du catalogue standardisé identifient les zones par un code
hiérarchique :

    SN              national
    SN-DK           région de Dakar
    SN-DK-PI        département de Pikine

Le préfixe porte le rattachement administratif : « SN-DK-PI » appartient
à « SN-DK » par simple troncature. La hiérarchie est donc déductible du
code, sans table de parenté.

Ce module sert deux usages :

  1. CRÉER les zones manquantes. population.xml couvre les 14 régions et
     les 46 départements — le chargement de ce seul fichier suffit à
     bâtir toute la hiérarchie administrative, sans attendre les 46 CSV
     du recensement. Les CSV viennent ensuite y greffer communes et
     quartiers.

  2. RATTACHER les observations SDMX aux zones existantes.


LES ALIAS SONT LE POINT CRITIQUE DE TOUT LE CHARGEMENT

Un libellé non reconnu ne provoque pas d'erreur : il crée une zone. Le
référentiel SDMX écrit « MALEM HODAR », les CSV du recensement écrivent
« MALEM HODDAR » — un D de différence — et le chargement produisait
47 départements au lieu de 46 : celui du référentiel vide, celui du CSV
portant les 228 quartiers. Rien ne signalait l'anomalie ailleurs que dans
le décompte final.

C'est pourquoi `controler()` compare désormais le nombre de départements
à 46 et nomme les suspects : un département né d'une variante
d'orthographe n'hérite que des lignes écrites avec cette variante, donc
il en a beaucoup moins que ses voisins, souvent aucune.

Vérification de l'alignement, à faire après chaque nouveau fichier :

    backend/.venv/bin/python backend/manage.py shell -c "
    from geography.models import Niveau, Zone
    for z in Zone.objects.filter(niveau=Niveau.DEPARTEMENT):
        n = Zone.objects.filter(code__startswith=z.code+'-',
                                niveau=Niveau.QUARTIER).count()
        if n == 0: print('SUSPECT', z.nom, z.code)
    "


VÉRIFICATION DES LIBELLÉS

Huit départements sont confirmés par les CSV déjà chargés (Dakar,
Guédiawaye, Keur Massar, Pikine, Rufisque, Bambey, Diourbel, Mbacké).
Les autres proviennent du découpage administratif du Sénégal et sont à
confirmer au fur et à mesure des chargements CSV : la fonction
`verifier_libelles()` signale tout écart.

Deux codes restent incertains et sont marqués INCERTAIN ci-dessous.
"""

import re


REGIONS = {
    "SN-DB": "DIOURBEL",
    "SN-DK": "DAKAR",
    "SN-FK": "FATICK",
    "SN-KA": "KAFFRINE",
    "SN-KD": "KOLDA",
    "SN-KE": "KEDOUGOU",
    "SN-KL": "KAOLACK",
    "SN-LG": "LOUGA",
    "SN-MT": "MATAM",
    "SN-SE": "SEDHIOU",
    "SN-SL": "SAINT-LOUIS",
    "SN-TC": "TAMBACOUNDA",
    "SN-TH": "THIES",
    "SN-ZG": "ZIGUINCHOR",
}

DEPARTEMENTS = {
    # Dakar — les cinq confirmés par les CSV
    "SN-DK-DD": "DAKAR",
    "SN-DK-GU": "GUEDIAWAYE",
    "SN-DK-KM": "KEUR MASSAR",
    "SN-DK-PI": "PIKINE",
    "SN-DK-RU": "RUFISQUE",

    # Diourbel — confirmés par les CSV
    "SN-DB-BA": "BAMBEY",
    "SN-DB-DD": "DIOURBEL",
    "SN-DB-MB": "MBACKE",

    # Fatick
    "SN-FK-FD": "FATICK",
    "SN-FK-FO": "FOUNDIOUGNE",
    "SN-FK-GO": "GOSSAS",

    # Kaffrine
    "SN-KA-BI": "BIRKELANE",
    "SN-KA-KA": "KAFFRINE",
    "SN-KA-KO": "KOUNGHEUL",
    "SN-KA-MH": "MALEM HODAR",

    # Kolda
    "SN-KD-KD": "KOLDA",
    "SN-KD-MY": "MEDINA YORO FOULAH",
    "SN-KD-VE": "VELINGARA",

    # Kédougou — SA / SL : attribution à confirmer (INCERTAIN)
    "SN-KE-KE": "KEDOUGOU",
    "SN-KE-SA": "SALEMATA",
    "SN-KE-SL": "SARAYA",

    # Kaolack
    "SN-KL-GU": "GUINGUINEO",
    "SN-KL-KA": "KAOLACK",
    "SN-KL-ND": "NIORO DU RIP",

    # Louga
    "SN-LG-KE": "KEBEMER",
    "SN-LG-LD": "LOUGA",
    "SN-LG-LI": "LINGUERE",

    # Matam
    "SN-MT-KA": "KANEL",
    "SN-MT-MA": "MATAM",
    "SN-MT-RF": "RANEROU FERLO",

    # Sédhiou
    "SN-SE-BO": "BOUNKILING",
    "SN-SE-GO": "GOUDOMP",
    "SN-SE-SD": "SEDHIOU",

    # Saint-Louis
    "SN-SL-DA": "DAGANA",
    "SN-SL-PO": "PODOR",
    "SN-SL-SD": "SAINT-LOUIS",

    # Tambacounda
    "SN-TC-BA": "BAKEL",
    "SN-TC-GO": "GOUDIRY",
    "SN-TC-KO": "KOUMPENTOUM",
    "SN-TC-TD": "TAMBACOUNDA",

    # Thiès
    "SN-TH-MB": "MBOUR",
    "SN-TH-TD": "THIES",
    "SN-TH-TI": "TIVAOUANE",

    # Ziguinchor
    "SN-ZG-BI": "BIGNONA",
    "SN-ZG-OU": "OUSSOUYE",
    "SN-ZG-ZD": "ZIGUINCHOR",
}

INCERTAINS = {"SN-KE-SA", "SN-KE-SL"}


# Variantes d'écriture rencontrées dans les CSV du recensement.
# Clé = forme comparable produite par _cle() : sans accents, sans
# apostrophes, sans espaces ni tirets. Valeur = libellé de référence,
# celui de DEPARTEMENTS ci-dessus.
#
# Chaque entrée manquante ici crée un département fantôme. Vérifié le
# 30/09/2026 : avec ces quatre alias, les 46 CSV se rattachent aux
# 46 départements du référentiel, aucun orphelin.
ALIAS = {
    "KOUPENTOUM": "KOUMPENTOUM",      # forme abrégée dans le CSV ANSD
    "NIORODURIP": "NIORO DU RIP",
    "NIORO": "NIORO DU RIP",
    "MALEMHODDAR": "MALEM HODAR",     # deux D dans les CSV, un au référentiel
}


def _cle(nom):
    from utils import norm
    return re.sub(r"['’`´\s-]+", "", norm(nom))


def canoniser(nom):
    """Ramène une variante d'écriture au libellé de référence."""
    from utils import norm
    return ALIAS.get(_cle(nom), norm(nom))


def normaliser(code):
    """Uniformise les variantes de notation rencontrées dans les exports."""
    return (code or "").upper().strip().replace("_", "-")


def parent_de(code):
    """SN-DK-PI -> SN-DK ; SN-DK -> SN ; SN -> None."""
    c = normaliser(code)
    parts = c.split("-")
    if len(parts) <= 1:
        return None
    return "-".join(parts[:-1])


def niveau_de(code):
    """Déduit le niveau administratif du nombre de segments."""
    n = len(normaliser(code).split("-"))
    return {1: "national", 2: "region", 3: "departement"}.get(n)


def construire_hierarchie():
    """
    Crée ou complète les zones nationales, régionales et départementales
    à partir de la table, et renseigne Zone.sdmx_code.

    Idempotent : relançable sans créer de doublon. Les zones déjà créées
    par les CSV sont retrouvées par leur code et simplement complétées.

    Retourne (créées, rattachées).
    """
    from geography.models import Niveau, Zone

    from utils import code_zone

    crees = rattachees = 0

    # --- national ---
    nat, cree = Zone.objects.get_or_create(
        code="SN",
        defaults={"nom": "SENEGAL", "niveau": Niveau.NATIONAL,
                  "parent": None},
    )
    if nat.sdmx_code != "SN":
        nat.sdmx_code = "SN"
        nat.save(update_fields=["sdmx_code"])
        rattachees += 1
    crees += int(cree)

    # --- régions ---
    par_code = {"SN": nat}
    for sdmx, nom in REGIONS.items():
        z, cree = Zone.objects.get_or_create(
            code=code_zone(nom),
            defaults={"nom": nom, "niveau": Niveau.REGION, "parent": nat},
        )
        crees += int(cree)
        if z.sdmx_code != sdmx:
            z.sdmx_code = sdmx
            z.save(update_fields=["sdmx_code"])
            rattachees += 1
        par_code[sdmx] = z

    # --- départements ---
    for sdmx, nom in DEPARTEMENTS.items():
        region = par_code.get(parent_de(sdmx))
        if region is None:
            continue
        z, cree = Zone.objects.get_or_create(
            code=code_zone(region.nom, nom),
            defaults={"nom": nom, "niveau": Niveau.DEPARTEMENT,
                      "parent": region},
        )
        crees += int(cree)
        if z.sdmx_code != sdmx:
            z.sdmx_code = sdmx
            z.save(update_fields=["sdmx_code"])
            rattachees += 1

    return crees, rattachees


def verifier_libelles():
    """
    Compare les libellés de la table aux noms issus des CSV du recensement.

    Un écart signifie soit une variante d'écriture bénigne, soit une
    correspondance de code erronée — à trancher au cas par cas.
    """
    from geography.models import Niveau, Zone

    from utils import norm

    ecarts = []
    attendus = {**REGIONS, **DEPARTEMENTS}

    for z in Zone.objects.exclude(sdmx_code="").filter(
        niveau__in=[Niveau.REGION, Niveau.DEPARTEMENT]
    ):
        attendu = attendus.get(z.sdmx_code)
        if attendu and norm(attendu) != norm(z.nom):
            ecarts.append({
                "code": z.sdmx_code,
                "table": attendu,
                "base": z.nom,
                "incertain": z.sdmx_code in INCERTAINS,
            })
    return ecarts