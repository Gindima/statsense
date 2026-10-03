"""
data/seed/geo.py

StatSense AI — Rattachement géographique et contrôles de cohérence

Le GeoJSON n'entre JAMAIS en base : pas de PostGIS, pas de sérialisation
de polygones à chaque requête. Le fichier reste statique, servi au
navigateur. Seul le code de jointure (SNDK, SNTH...) est stocké dans
Zone.geojson_id.


DEUX NATURES D'ANOMALIES, DEUX TRAITEMENTS

La version précédente les confondait, et `make seed` renvoyait 1 parce
qu'un village de Kébémer avait, dans le fichier publié, un total qui ne
correspondait pas à la somme des hommes et des femmes. Dans un
`docker compose`, une étape de chargement qui renvoie 1 empêche le
démarrage : un défaut de la source aurait rendu la plateforme
indéployable.

  ANOMALIE BLOQUANTE — le chargement a échoué. Régions manquantes, zones
  orphelines, indicateur sans observation, régions sans geojson_id. Ces
  cas signalent un bug ou un fichier absent, et il faut s'arrêter.

  AVERTISSEMENT — les données publiées sont incohérentes, et nous n'y
  pouvons rien. Une ligne où hommes + femmes ≠ population, un effectif
  négatif. Il faut les nommer, les afficher, éventuellement les citer en
  note méthodologique — mais pas refuser de démarrer.

La règle : on bloque sur ce qu'on peut corriger, on signale ce qu'on ne
peut que constater.
"""

import json
from pathlib import Path

from catalog.models import Indicateur
from geography.models import Niveau, Zone
from observations.models import Observation

from utils import norm

CHAMPS_NOM = ("name", "NAME_1", "nom", "shapeName", "admin1Name")
CHAMPS_CODE = ("id", "code", "hasc", "HASC_1", "shapeISO", "iso_3166_2")

# Nombre de départements du découpage administratif en vigueur. Sert à
# détecter un département fantôme né d'une variante d'orthographe.
DEPARTEMENTS_ATTENDUS = 46


def rattacher_geojson(chemin="data/raw/geo/sn.json"):
    """
    Renseigne Zone.geojson_id pour les 14 régions.

    Échoue bruyamment si une région du GeoJSON ne trouve pas sa zone :
    un polygone orphelin est un trou blanc sur la carte, et on préfère
    le découvrir ici plutôt qu'en démonstration.
    """
    data = json.loads(Path(chemin).read_text(encoding="utf-8"))
    regions = {norm(z.nom): z for z in Zone.objects.filter(niveau=Niveau.REGION)}

    apparies, orphelins = 0, []

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        nom = next((props[c] for c in CHAMPS_NOM if props.get(c)), None)
        code = next((props[c] for c in CHAMPS_CODE if props.get(c)), None)

        if not nom:
            continue

        zone = regions.get(norm(nom))
        if zone is None:
            orphelins.append(nom)
            continue

        zone.geojson_id = (code or norm(nom))[:10]
        zone.save(update_fields=["geojson_id"])
        apparies += 1

    sans_code = [z.nom for z in Zone.objects.filter(
        niveau=Niveau.REGION, geojson_id="")]

    return {"apparies": apparies, "orphelins": orphelins,
            "regions_sans_code": sans_code}


def controler():
    """
    Contrôles post-chargement.

    Retourne (rapport, anomalies). `anomalies` ne contient que ce qui
    justifie d'interrompre : l'appelant en fait un code de sortie non nul.
    Ce qui relève de la qualité des données publiées est rangé dans
    `rapport["avertissements"]`, affiché mais non bloquant.
    """
    anomalies = []
    avertissements = []

    par_niveau = {n: Zone.objects.filter(niveau=n).count()
                  for n, _ in Niveau.choices}

    # --- bloquant : la hiérarchie doit être complète et cohérente -------

    if par_niveau.get(Niveau.REGION, 0) != 14:
        anomalies.append(
            f"{par_niveau.get(Niveau.REGION, 0)} régions au lieu de 14")

    nb_dept = par_niveau.get(Niveau.DEPARTEMENT, 0)
    if nb_dept != DEPARTEMENTS_ATTENDUS:
        # Un département de trop vient presque toujours d'une variante
        # d'orthographe qu'aucun alias ne ramène à sa forme de référence.
        # On nomme les suspects : ceux qui portent le moins de quartiers.
        suspects = _departements_suspects()
        detail = ", ".join(f"{nom} ({n} quartiers)" for nom, n in suspects)
        anomalies.append(
            f"{nb_dept} départements au lieu de {DEPARTEMENTS_ATTENDUS}"
            + (f" — à vérifier : {detail}" if detail else "")
        )

    orphelines = Zone.objects.filter(
        parent__isnull=True
    ).exclude(niveau__in=[Niveau.REGION, Niveau.NATIONAL]).count()
    if orphelines:
        anomalies.append(f"{orphelines} zones sans parent")

    sans_geo = Zone.objects.filter(niveau=Niveau.REGION,
                                   geojson_id="").count()
    if sans_geo:
        anomalies.append(f"{sans_geo} régions sans geojson_id")

    stockes = Indicateur.objects.filter(derive_de="")
    vides = [i.code for i in stockes if not i.observations.exists()]
    if vides:
        anomalies.append(f"indicateurs sans observation : {', '.join(vides)}")

    # --- avertissements : défauts de la source, non corrigeables ---------

    negatives = Observation.objects.filter(
        valeur__lt=0, indicateur__unite="personnes").count()
    if negatives:
        avertissements.append(f"{negatives} effectifs négatifs dans la source")

    incoherentes = _zones_sexes_incoherentes()
    if incoherentes:
        apercu = "; ".join(
            f"{nom} (H+F={hf}, total={t}, écart {hf - t:+d})"
            for nom, hf, t in incoherentes[:3]
        )
        suite = f" et {len(incoherentes) - 3} autre(s)" \
            if len(incoherentes) > 3 else ""
        avertissements.append(
            f"{len(incoherentes)} zone(s) où hommes + femmes ≠ population "
            f"dans les fichiers publiés : {apercu}{suite}"
        )

    rapport = {
        "zones": par_niveau,
        "observations": Observation.objects.count(),
        "indicateurs": Indicateur.objects.count(),
        "population_nationale": _population_nationale(),
        "avertissements": avertissements,
    }
    return rapport, anomalies


def _departements_suspects(limite=3):
    """
    Départements portant le moins de quartiers.

    Un département né d'une variante d'orthographe n'hérite que des lignes
    écrites avec cette variante : il en a donc beaucoup moins que ses
    voisins, souvent aucune.
    """
    out = []
    for z in Zone.objects.filter(niveau=Niveau.DEPARTEMENT):
        n = Zone.objects.filter(code__startswith=f"{z.code}-",
                                niveau=Niveau.QUARTIER).count()
        out.append((z.nom, n))
    out.sort(key=lambda t: t[1])
    return out[:limite]


def _zones_sexes_incoherentes(tolerance=1):
    """
    Zones où l'addition des sexes ne reconstitue pas le total publié.

    Retourne des triplets (nom, hommes + femmes, total) plutôt qu'un
    simple décompte : une anomalie que l'on ne peut pas corriger doit au
    moins pouvoir être citée.
    """
    par_zone = {}
    for o in Observation.objects.filter(
        indicateur__code="pop_totale", periode="2023"
    ).values("zone_id", "dims", "valeur"):
        sexe = (o["dims"] or {}).get("sexe", "T")
        par_zone.setdefault(o["zone_id"], {})[sexe] = o["valeur"]

    suspectes = []
    for zone_id, v in par_zone.items():
        if not {"T", "H", "F"} <= set(v):
            continue
        hf = v["H"] + v["F"]
        if abs(hf - v["T"]) > tolerance:
            suspectes.append((zone_id, int(hf), int(v["T"])))

    if not suspectes:
        return []

    noms = dict(
        Zone.objects.filter(id__in=[z for z, _, _ in suspectes])
        .values_list("id", "nom")
    )
    return [(noms.get(z, str(z)), hf, t) for z, hf, t in suspectes]


def _population_nationale():
    from django.db.models import Sum
    r = Observation.objects.filter(
        indicateur__code="pop_totale",
        periode="2023",
        dims={},
        zone__niveau=Niveau.QUARTIER,
    ).aggregate(t=Sum("valeur"))
    return int(r["t"]) if r["t"] else 0