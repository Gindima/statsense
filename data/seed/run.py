#!/usr/bin/env python
"""
data/seed/run.py

StatSense AI — Point d'entrée du chargement de données

    python data/seed/run.py --rebuild     vide tout et recharge (défaut)
    python data/seed/run.py --append      charge seulement le nouveau
    python data/seed/run.py --controle    contrôles seuls, sans écrire

MODE REBUILD
    Reconstruction complète. Déterministe : même contenu de data/raw,
    même base, toujours. Prend une trentaine de secondes à cette échelle.
    C'est le mode à utiliser dès que quelque chose semble incohérent.

MODE APPEND
    Pour une collecte progressive : les 46 départements téléchargés sur
    plusieurs jours. Un fichier déjà chargé est ignoré, un fichier modifié
    est rechargé, un nouveau fichier est ajouté.

    L'enregistrement Chargement n'est créé qu'APRÈS succès complet du
    fichier, dans une transaction : une interruption ne laisse aucun
    état incohérent.


CODE DE SORTIE

    0  le chargement a abouti, même si les données publiées comportent
       des incohérences que l'on ne peut que signaler
    1  le chargement a échoué : hiérarchie incomplète, indicateur sans
       observation, région sans polygone

La distinction n'est pas cosmétique. Ce script est appelé au démarrage
d'un conteneur ; renvoyer 1 parce qu'un village de Kébémer a, dans le
fichier publié, un total qui ne correspond pas à la somme des sexes
rendrait la plateforme indéployable. On bloque sur ce qu'on peut
corriger, on signale ce qu'on ne peut que constater.
"""

import argparse
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()

from django.db import transaction  # noqa: E402

from catalog.models import Chargement, Indicateur, Source  # noqa: E402
from geography.models import Zone  # noqa: E402
from observations.models import Observation  # noqa: E402

from catalogue import CATALOGUE, SOURCES, controler as controler_catalogue  # noqa: E402
from csv_rgph import ChargeurRGPH, fichiers_rgph  # noqa: E402
from sdmx import ChargeurSDMX, fichiers_sdmx  # noqa: E402
from geo import controler, rattacher_geojson  # noqa: E402
from utils import empreinte  # noqa: E402
from zones_sdmx import construire_hierarchie, verifier_libelles  # noqa: E402
from sdmx21 import ChargeurSDMX21, est_sdmx21  # noqa: E402


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

def charger_catalogue():
    """Le catalogue précède tout : les chargeurs résolvent les codes dessus."""
    controler_catalogue()          # échoue avant d'écrire quoi que ce soit

    for cle, s in SOURCES.items():
        Source.objects.update_or_create(
            cle=cle,
            defaults={"nom": s["nom"], "url": s["url"],
                      "plateforme": s["plateforme"],
                      "date_extraction": s["date_extraction"],
                      "note": s.get("note", "")},
        )

    sources = {s.cle: s for s in Source.objects.all()}

    for i in CATALOGUE:
        Indicateur.objects.update_or_create(
            code=i["code"],
            defaults={
                "libelle": i["libelle"],
                "synonymes": i["synonymes"],
                "unite": i["unite"],
                "dimensions": i.get("dimensions", []),
                "agregeable": i["agregeable"],
                "granularite_geo_min": i["granularite_geo_min"],
                "frequence": i["frequence"],
                "comparaison_defaut": i.get("comparaison_defaut"),
                "prix_base": i.get("prix_base", "") or "",
                "derive_de": i.get("derive_de", "") or "",
                "niveau_sectoriel": i.get("niveau_sectoriel", "") or "",
                "source": sources[i["source"]],
            },
        )

    # Second passage : les parents sectoriels référencent d'autres indicateurs.
    codes = {i.code: i for i in Indicateur.objects.all()}
    for i in CATALOGUE:
        parent = i.get("secteur_parent")
        if parent and parent in codes:
            obj = codes[i["code"]]
            obj.secteur_parent = codes[parent]
            obj.save(update_fields=["secteur_parent"])

    return Indicateur.objects.count()


# ---------------------------------------------------------------------------
# Chargement d'un fichier
# ---------------------------------------------------------------------------

def charger_fichier(chemin, chargeur, mode):
    """
    Retourne un Compteur, ou None si le fichier est ignoré en mode append.
    Tout se fait dans une transaction : succès complet ou rien.
    """
    nom = Path(chemin).name
    h = empreinte(chemin)
    deja = Chargement.objects.filter(fichier=nom).first()

    if mode == "append" and deja:
        if deja.empreinte == h:
            print(f"  ⏭  {nom:32} déjà chargé")
            return None
        print(f"  ♻  {nom:32} modifié, rechargement")
        deja.delete()               # cascade sur les observations liées

    with transaction.atomic():
        chargement = Chargement.objects.create(
            fichier=nom, empreinte=h, lignes_lues=0,
            zones_creees=0, observations_creees=0,
        )
        compteur = chargeur.charger(chemin, chargement)
        chargement.lignes_lues = compteur.lignes
        chargement.zones_creees = compteur.zones
        chargement.observations_creees = compteur.observations
        chargement.save()

    return compteur


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def purger():
    print("  Suppression des données existantes...")
    Observation.objects.all().delete()
    Zone.objects.all().delete()
    Chargement.objects.all().delete()
    Indicateur.objects.all().delete()    # avant Source : FK en PROTECT
    Source.objects.all().delete()


def executer(mode):
    debut = time.time()
    print(f"\n{'=' * 62}\n  StatSense AI — chargement ({mode})\n{'=' * 62}\n")

    if mode == "rebuild":
        purger()

    print("→ Catalogue")
    print(f"  {charger_catalogue()} indicateurs, "
          f"{Source.objects.count()} sources\n")

    print("→ Hiérarchie administrative")
    crees, rattachees = construire_hierarchie()
    print(f"  {crees} zones créées, {rattachees} rattachées")
    # Écarts entre la table de référence et les libellés reçus. Déplacé
    # ici depuis le corps du module : au niveau du module, ces lignes
    # s'affichaient avant l'en-tête, y compris pour `--help`.
    for e in verifier_libelles():
        marque = "⚠ INCERTAIN" if e["incertain"] else "  écart"
        print(f"  {marque} {e['code']} : table={e['table']} base={e['base']}")
    print()

    print("→ Recensement RGPH 2023")
    fichiers = fichiers_rgph(RACINE / "data/raw/rgph2023")
    if not fichiers:
        print("  ⚠  aucun CSV trouvé dans data/raw/rgph2023/")
    else:
        chargeur = ChargeurRGPH()
        for f in fichiers:
            c = charger_fichier(f, chargeur, mode)
            if c:
                print(c.ligne_rapport())
                for e in c.erreurs[:5]:
                    print(e)
    print()

    print("→ Séries SDMX")
    fichiers = fichiers_sdmx(RACINE / "data/raw/sdmx")
    if not fichiers:
        print("  ⚠  aucun fichier trouvé dans data/raw/sdmx/")
    else:
        cpt, c21 = ChargeurSDMX(), ChargeurSDMX21()
        for f in fichiers:
            chargeur = c21 if est_sdmx21(f) else cpt
            c = charger_fichier(f, chargeur, mode)
            if c:
                print(c.ligne_rapport())
                for e in c.erreurs[:5]:
                    print(e)
    print()

    print("→ Rattachement du GeoJSON")
    geo = RACINE / "data/raw/geo/sn.json"
    if geo.exists():
        r = rattacher_geojson(geo)
        print(f"  {r['apparies']} régions rattachées")
        if r["orphelins"]:
            print(f"  ⚠  polygones sans zone : {r['orphelins']}")
        if r["regions_sans_code"]:
            print(f"  ⚠  régions sans code : {r['regions_sans_code']}")
    else:
        print("  ⚠  data/raw/geo/sn.json introuvable")
    print()

    return rapport_final(debut)


def rapport_final(debut=None):
    rapport, anomalies = controler()

    print(f"{'=' * 62}\n  RÉSULTAT\n{'=' * 62}")
    for niveau, n in rapport["zones"].items():
        if n:
            print(f"  {niveau:14} {n:>8}")
    print(f"  {'observations':14} {rapport['observations']:>8}")
    print(f"  {'indicateurs':14} {rapport['indicateurs']:>8}")
    print(f"\n  Population nationale (somme des quartiers) : "
          f"{rapport['population_nationale']:,}".replace(",", " "))

    # Défauts des données publiées : à connaître et à citer, mais ils
    # n'empêchent pas la plateforme de fonctionner.
    for a in rapport.get("avertissements", []):
        print(f"\n  ⓘ  {a}")

    if anomalies:
        print("\n  ✗  LE CHARGEMENT A ÉCHOUÉ")
        for a in anomalies:
            print(f"     - {a}")
    else:
        print("\n  ✓  Chargement complet")

    if debut:
        print(f"\n  Durée : {time.time() - debut:.1f}s")
    print()

    return 1 if anomalies else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Chargement des données StatSense AI")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--rebuild", action="store_true",
                   help="vide et recharge tout (défaut)")
    g.add_argument("--append", action="store_true",
                   help="charge uniquement les fichiers nouveaux ou modifiés")
    g.add_argument("--controle", action="store_true",
                   help="contrôles de cohérence seuls, aucune écriture")
    args = p.parse_args()

    if args.controle:
        sys.exit(rapport_final())
    sys.exit(executer("append" if args.append else "rebuild"))