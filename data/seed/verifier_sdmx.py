"""
data/seed/verifier_sdmx.py

StatSense AI — Cohérence interne des fichiers SDMX 2.1

    backend/.venv/bin/python data/seed/verifier_sdmx.py

N'écrit rien, ne touche pas à la base. Lit les fichiers de data/raw/sdmx
et applique deux contrôles qui ne dépendent d'aucune hypothèse sur les
valeurs attendues.


CONTRÔLE 1 — CONCORDANCE DES ATTRIBUTS GÉOGRAPHIQUES

Chaque série porte plusieurs attributs de zone : R-GIONS, ID_RÉGIONS…,
REGIONID_RÉGIONS…. Ils devraient désigner la même zone. Dans
population.xml ils diffèrent :

    ligne à 2 587 092   R-GIONS = SN-KD    REGIONID_… = SN-KE-KE-CU
    ligne à 1 415 481   R-GIONS = SN-KE    REGIONID_… = SN-KD

SN-KE-KE-CU est un code de commune sur une ligne de région. Un taux de
désaccord élevé signale un export dont la dimension géographique a
glissé.


CONTRÔLE 2 — LE TOTAL CONTRE SES PARTIES

Pour un indicateur sommable ventilé par sexe, la série « _T » doit égaler
la somme de « M » et « F », à la même zone, la même période et la même
tranche d'âge. C'est vérifiable sans connaître le Sénégal.

Dans population.xml :

    SN-TH  sexe=_T  →    259 268
    SN-TH  sexe=M   →  1 321 204

Un total inférieur à sa propre composante masculine. Le fichier se
contredit.

Ce contrôle ne s'applique qu'aux effectifs. Un taux ou un indice ne
s'additionne pas entre modalités, et l'absence d'anomalie y sera donc
muette — le contrôle 1 reste alors le seul indice.


CE QUE LA SORTIE PERMET DE DÉCIDER

Un fichier qui échoue aux deux contrôles ne doit pas être publié, quelle
que soit la beauté de ses chiffres. Un fichier qui passe les deux peut
l'être. Un fichier qui n'échoue qu'au premier demande un examen : le
désaccord peut venir d'un attribut décoratif que le chargeur n'utilise
pas.
"""

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

RACINE = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/sdmx")

# Ce que le chargeur lit réellement, dans cet ordre (cf. sdmx21.GEO).
GEO_PRINCIPAUX = ("R_GIONS", "R-GIONS", "R_GION", "R-GION",
                  "RÉGIONS", "RÉGION", "REGIONS", "REGION", "REF_AREA")

TOTAUX = {"_T", "_Z", "Ens", "ENS", ""}

# Indicateurs en effectifs : le total doit égaler la somme des sexes.
# Un taux, un indice ou un pourcentage ne s'additionne pas.
SOMMABLES = {"population"}


def _local(tag):
    return tag.split("}")[-1]


def _attributs_geo(serie):
    """Toutes les valeurs d'attributs qui ressemblent à un code de zone."""
    out = {}
    for k, v in serie.attrib.items():
        if not v:
            continue
        s = str(v).strip()
        if s.upper().startswith("SN"):
            out[k] = s
    return out


def _lu_par_le_chargeur(serie):
    for attr in GEO_PRINCIPAUX:
        v = serie.get(attr)
        if v:
            return v.strip()
    for k, v in serie.attrib.items():
        if not k.startswith(("ID_", "REGIONID_", "F2_")) \
                and str(v).upper().startswith("SN"):
            return str(v).strip()
    return None


def _sexe(serie):
    for k in ("SEXE", "ID_SEXE"):
        v = serie.get(k)
        if v:
            return v.strip()
    return None


def _age(serie):
    for k, v in serie.attrib.items():
        if "GE" in k.upper() and "GROUPE" in k.upper() and not k.startswith("ID_"):
            return (v or "").strip()
    return ""


def analyser(chemin):
    racine = ET.parse(chemin).getroot()

    series = 0
    desaccords = 0
    exemples_desaccord = []

    # (zone, periode, age) -> {sexe: valeur}
    par_cle = defaultdict(dict)

    for serie in racine.iter():
        if _local(serie.tag) != "Series":
            continue
        series += 1

        geo = _attributs_geo(serie)
        distinctes = set(geo.values())
        if len(distinctes) > 1:
            desaccords += 1
            if len(exemples_desaccord) < 3:
                exemples_desaccord.append(geo)

        zone = _lu_par_le_chargeur(serie)
        sexe = _sexe(serie)
        age = _age(serie)
        if zone is None or sexe is None:
            continue

        for obs in serie:
            if _local(obs.tag) != "Obs":
                continue
            per = obs.get("TIME_PERIOD")
            val = obs.get("OBS_VALUE")
            if not per or not val:
                continue
            try:
                v = float(val)
            except ValueError:
                continue
            par_cle[(zone, per.strip(), age)][sexe] = v

    # contrôle 2
    testes = incoherents = 0
    exemples_somme = []
    for (zone, per, age), v in par_cle.items():
        t = next((v[s] for s in ("_T", "_Z", "Ens", "ENS") if s in v), None)
        h = v.get("M") or v.get("H")
        f = v.get("F")
        if t is None or h is None or f is None:
            continue
        testes += 1
        if t <= 0:
            continue
        if abs((h + f) - t) / t > 0.005:
            incoherents += 1
            if len(exemples_somme) < 3:
                exemples_somme.append((zone, per, age, t, h, f))

    return {
        "fichier": chemin.name,
        "series": series,
        "desaccords": desaccords,
        "exemples_desaccord": exemples_desaccord,
        "testes": testes,
        "incoherents": incoherents,
        "exemples_somme": exemples_somme,
    }


def main():
    fichiers = sorted(list(RACINE.glob("*.xml")) + list(RACINE.glob("*.sdmx")))
    fichiers = [f for f in fichiers
                if "StructureSpecificData" in
                f.read_text(encoding="utf-8", errors="replace")[:2000]]

    if not fichiers:
        print(f"Aucun fichier SDMX 2.1 dans {RACINE}")
        raise SystemExit(1)

    print()
    print("=" * 88)
    print(f"  {len(fichiers)} fichier(s) SDMX 2.1 dans {RACINE}")
    print("=" * 88)
    print(f"  {'fichier':22} {'séries':>7} {'désaccord géo':>16} "
          f"{'total ≠ M+F':>16}")
    print("  " + "-" * 84)

    rapports = []
    for f in fichiers:
        try:
            r = analyser(f)
        except Exception as e:
            print(f"  {f.name:22} ERREUR : {e}")
            continue
        rapports.append(r)

        pct_geo = (100 * r["desaccords"] / r["series"]) if r["series"] else 0
        somme = (f"{r['incoherents']}/{r['testes']}"
                 if r["testes"] else "non applicable")
        marque = ""
        if r["incoherents"]:
            marque = "  ✗ À NE PAS PUBLIER"
        elif pct_geo > 5:
            marque = "  ⚠ à examiner"
        print(f"  {r['fichier']:22} {r['series']:>7} "
              f"{r['desaccords']:>6} ({pct_geo:>4.0f} %) "
              f"{somme:>16}{marque}")

    print()
    print("=" * 88)
    print("  DÉTAIL")
    print("=" * 88)

    for r in rapports:
        if not (r["exemples_desaccord"] or r["exemples_somme"]):
            continue
        print(f"\n  {r['fichier']}")
        for geo in r["exemples_desaccord"]:
            print("    attributs de zone en désaccord :")
            for k, v in sorted(geo.items()):
                print(f"      {k:46} {v}")
        for zone, per, age, t, h, f in r["exemples_somme"]:
            tranche = age or "_T"
            print(f"    {zone} · {per} · âge {tranche} : "
                  f"total {t:,.0f} ≠ {h:,.0f} + {f:,.0f} = {h + f:,.0f}"
                  .replace(",", " "))

    print()
    print("=" * 88)
    print("  LECTURE")
    print("=" * 88)
    print("""
  Un fichier marqué « À NE PAS PUBLIER » se contredit : son total ne
  vaut pas la somme de ses parties, à zone, période et âge identiques.
  Aucune correspondance de codes ne répare ça, et deviner la bonne
  attribution serait inventer une donnée.

  Un fichier marqué « à examiner » a des attributs de zone divergents
  sans incohérence arithmétique décelable. Sur un taux ou un indice, le
  contrôle 2 est muet : le désaccord d'attributs est alors le seul
  indice, et il faut comparer quelques valeurs régionales à une
  publication de l'ANSD avant de conclure.

  Un fichier sans marque passe les deux contrôles disponibles.
""")


main()