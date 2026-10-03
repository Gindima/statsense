#!/usr/bin/env python3
"""
Inventaire des fichiers SDMX 2.1 — diagnostic, sans Django.

    python3 data/seed/inventaire.py

Affiche pour chaque fichier ses dimensions, leurs valeurs, ses codes
géographiques et sa couverture temporelle. C'est ce qui permet de
calibrer la table FICHIERS de sdmx21.py et d'étendre le catalogue.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RACINE = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/sdmx")

IGNORES = {"FREQ", "TIME_FORMAT", "UNIT_MULT", "UNIT_MEASURE",
           "OBS_STATUS", "DECIMALS", "BASE_PER"}


def local(tag):
    return tag.split("}")[-1]


def utile(attr):
    """Écarte les doublons ID_* / REGIONID_* et les attributs techniques."""
    return not attr.startswith(("ID_", "REGIONID_")) and attr not in IGNORES


for f in sorted(RACINE.glob("*.xml")):
    try:
        racine = ET.parse(f).getroot()
    except ET.ParseError as e:
        print(f"\n=== {f.name}  ⚠ illisible : {e}")
        continue

    series = [s for s in racine.iter() if local(s.tag) == "Series"]
    print(f"\n=== {f.name}")
    print(f"    racine   {local(racine.tag)}   séries {len(series)}")

    if not series:
        continue

    valeurs, periodes = {}, set()
    for s in series:
        for attr, v in s.attrib.items():
            if utile(attr):
                valeurs.setdefault(attr, set()).add(v)
        for o in s:
            if local(o.tag) == "Obs" and o.get("TIME_PERIOD"):
                periodes.add(o.get("TIME_PERIOD"))

    for attr, vals in sorted(valeurs.items()):
        v = sorted(vals)
        apercu = v if len(v) <= 12 else v[:12] + [f"… (+{len(v) - 12})"]
        print(f"    {attr:24} {apercu}")

    if periodes:
        print(f"    {'PÉRIODES':24} {min(periodes)} → {max(periodes)}"
              f"  ({len(periodes)} points)")