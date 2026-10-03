"""
data/seed/verifier_csv.py

StatSense AI — Ce que contiennent vraiment les CSV du RGPH

À lancer ainsi, depuis la racine du projet, SANS Django :

    backend/.venv/bin/python data/seed/verifier_csv.py

Ne touche ni à la base ni aux fichiers. Lit les CSV et répond à une seule
question : que va produire le chargement, et pourquoi.

POURQUOI CE SCRIPT EXISTE

Le chargeur signalait des observations « ignorées » et le total national
accusait 1 372 habitants de moins que la publication de l'ANSD. On en a
conclu que des villages homonymes s'écrasaient mutuellement, et un
correctif a été écrit pour les numéroter.

Vérification faite sur ziguinchor.csv : les 76 lignes en cause sont des
doublons EXACTS sur les onze colonnes — la même ligne répétée. Les
numéroter aurait créé 76 villages fantômes et ajouté 27 673 habitants
qui n'existent pas. Le correctif aggravait le problème qu'il prétendait
résoudre, et le compteur d'« ignorées » signalait en réalité que le
garde-fou fonctionnait.

D'où la règle, qui se lit dans les données et ne se devine pas :

  - même clé géographique ET mêmes chiffres  -> doublon, à écarter ;
  - même clé géographique ET chiffres différents -> homonymes réels,
    à distinguer.

Ce script compte les deux cas, fichier par fichier, et chiffre l'écart
que chaque politique produirait sur le total national. Il compte aussi
les lignes écartées pour hiérarchie incomplète, qui sont l'autre
explication possible du déficit.
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

RACINE = sys.argv[1] if len(sys.argv) > 1 else "data/raw/rgph2023"

CLE = ("Region", "Departement", "COMMUNE", "QUARTIER_VILLAGE_HAMEAU")
CHIFFRES = ("CONCESSION", "MENAGE", "HOMMES", "FEMMES", "POPULATION")

# Total publié par l'ANSD pour le RGPH 2023, pour comparaison.
OFFICIEL = 18_126_390


def entier(v):
    try:
        return int(str(v).strip().replace(" ", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def analyser(chemin):
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        lignes = list(csv.DictReader(f))

    groupes = defaultdict(list)
    incompletes = []
    pop_illisible = []

    for n, r in enumerate(lignes, start=2):
        if not all((r.get(k) or "").strip() for k in CLE):
            incompletes.append((n, {k: r.get(k) for k in CLE}))
            continue
        if entier(r.get("POPULATION")) is None:
            pop_illisible.append((n, r.get("POPULATION")))
            continue
        groupes[tuple((r[k] or "").strip().upper() for k in CLE)].append(r)

    doublons = homonymes = 0
    pop_doublons = pop_homonymes = 0
    exemples_homonymes = []

    for cle, g in groupes.items():
        if len(g) == 1:
            continue
        signatures = {}
        for r in g:
            sig = tuple((r.get(c) or "").strip() for c in CHIFFRES)
            signatures.setdefault(sig, 0)
            signatures[sig] += 1

        # Répétitions à l'identique : tout ce qui dépasse le premier
        # exemplaire de chaque signature.
        for sig, k in signatures.items():
            if k > 1:
                doublons += k - 1
                pop = entier(sig[CHIFFRES.index("POPULATION")]) or 0
                pop_doublons += pop * (k - 1)

        # Signatures distinctes sous la même clé : homonymes réels.
        if len(signatures) > 1:
            homonymes += len(signatures) - 1
            pops = sorted(entier(s[CHIFFRES.index("POPULATION")]) or 0
                          for s in signatures)
            pop_homonymes += sum(pops[:-1])
            if len(exemples_homonymes) < 4:
                exemples_homonymes.append((cle[2], cle[3], pops))

    pop_brute = sum(entier(r.get("POPULATION")) or 0 for r in lignes)
    pop_incompletes = sum(entier(r.get("POPULATION")) or 0
                          for n, _ in incompletes
                          for r in [lignes[n - 2]])

    return {
        "fichier": Path(chemin).name,
        "lignes": len(lignes),
        "cles": len(groupes),
        "doublons": doublons,
        "pop_doublons": pop_doublons,
        "homonymes": homonymes,
        "pop_homonymes": pop_homonymes,
        "incompletes": len(incompletes),
        "pop_incompletes": pop_incompletes,
        "illisibles": len(pop_illisible),
        "pop_brute": pop_brute,
        "exemples": exemples_homonymes,
        "detail_incompletes": incompletes[:3],
    }


def main():
    fichiers = sorted(Path(RACINE).glob("*.csv"))
    if not fichiers:
        print(f"Aucun CSV dans {RACINE}")
        raise SystemExit(1)

    print()
    print("=" * 96)
    print(f"  {len(fichiers)} fichier(s) dans {RACINE}")
    print("=" * 96)
    print(f"  {'fichier':<26} {'lignes':>7} {'doubl.':>7} {'homon.':>7} "
          f"{'incompl.':>9} {'pop brute':>12}")
    print("  " + "-" * 92)

    tot = defaultdict(int)
    exemples = []
    incompletes_detail = []

    for f in fichiers:
        try:
            a = analyser(f)
        except Exception as e:
            print(f"  {f.name:<26} ERREUR : {e}")
            continue

        marque = ""
        if a["homonymes"]:
            marque = "  <- homonymes réels"
        print(f"  {a['fichier']:<26} {a['lignes']:>7} {a['doublons']:>7} "
              f"{a['homonymes']:>7} {a['incompletes']:>9} "
              f"{a['pop_brute']:>12,}".replace(",", " ") + marque)

        for c in ("lignes", "doublons", "pop_doublons", "homonymes",
                  "pop_homonymes", "incompletes", "pop_incompletes",
                  "illisibles", "pop_brute"):
            tot[c] += a[c]
        exemples.extend(a["exemples"])
        if a["detail_incompletes"]:
            incompletes_detail.append((a["fichier"],
                                       a["detail_incompletes"]))

    print("  " + "-" * 92)
    print(f"  {'TOTAL':<26} {tot['lignes']:>7} {tot['doublons']:>7} "
          f"{tot['homonymes']:>7} {tot['incompletes']:>9} "
          f"{tot['pop_brute']:>12,}".replace(",", " "))

    print()
    print("=" * 96)
    print("  CE QUE CHAQUE POLITIQUE DONNERAIT")
    print("=" * 96)

    brute = tot["pop_brute"]
    dedup = brute - tot["pop_doublons"]
    numerote = brute  # tout est conservé, doublons compris

    def ligne(nom, valeur):
        ecart = valeur - OFFICIEL
        signe = "+" if ecart > 0 else ""
        print(f"  {nom:<52} {valeur:>12,}".replace(",", " ")
              + f"   écart {signe}{ecart:,}".replace(",", " "))

    print(f"  {'publication ANSD (RGPH 2023)':<52} "
          f"{OFFICIEL:>12,}".replace(",", " "))
    print()
    ligne("somme brute de toutes les lignes", brute)
    ligne("doublons exacts écartés  <- politique correcte", dedup)
    ligne("tous les homonymes numérotés (correctif erroné)", numerote)

    print()
    print(f"  population des lignes à hiérarchie incomplète : "
          f"{tot['pop_incompletes']:,}".replace(",", " "))
    print(f"  lignes dont POPULATION est illisible           : "
          f"{tot['illisibles']}")

    if exemples:
        print()
        print("=" * 96)
        print("  HOMONYMES RÉELS (même clé, chiffres différents)")
        print("=" * 96)
        print("  Ceux-là, et eux seuls, doivent être numérotés.")
        for commune, quartier, pops in exemples[:12]:
            montre = " / ".join(f"{p:,}".replace(",", " ") for p in pops)
            print(f"    {commune} / {quartier} : {montre}")
    else:
        print()
        print("  AUCUN homonyme réel dans l'ensemble des fichiers.")
        print("  La numérotation est donc inutile : il suffit d'écarter")
        print("  les doublons exacts.")

    if incompletes_detail:
        print()
        print("=" * 96)
        print("  LIGNES ÉCARTÉES POUR HIÉRARCHIE INCOMPLÈTE")
        print("=" * 96)
        print("  Ce sont elles qui expliquent un déficit résiduel.")
        for fichier, det in incompletes_detail[:6]:
            print(f"    {fichier}")
            for n, cle in det:
                print(f"      ligne {n} : {cle}")

    print()


main()