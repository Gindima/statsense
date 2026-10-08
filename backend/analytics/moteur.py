"""
backend/analytics/moteur.py

StatSense AI — Moteur analytique

Quatre méthodes, une signature commune : plan -> AnalysisResult.

AUCUN appel au modèle de langage ici. Les mêmes entrées produisent
toujours les mêmes sorties. C'est ce qui rend les chiffres exacts et
reproductibles, et c'est la moitié du projet.

Les règles méthodologiques vivent dans ce fichier, jamais dans un
prompt : une règle confiée à un système probabiliste est une règle
parfois ignorée.


LE RELAIS ENTRE SÉRIES ÉQUIVALENTES

`executer()` fait une seconde tentative quand l'indicateur retenu ne peut
pas servir le plan et qu'une série équivalente est déclarée. Trois motifs
seulement y donnent droit — période non couverte, série trop courte,
indicateur sans données — parce que ce sont les trois cas où l'échec vient
de la COUVERTURE de la série et non de la demande elle-même.

Trois issues possibles, et aucune n'est muette :

    la seconde tentative réussit   -> le résultat porte en première note
                                      la série employée et le motif qui a
                                      écarté la première

    elle échoue à son tour         -> le refus relevé est celui d'ORIGINE,
                                      complété par ce que la série de
                                      relais ne pouvait pas faire non plus

    aucune série équivalente       -> le refus d'origine, tel quel

Le deuxième cas est le plus important pour la qualité des réponses. Sur
« la population de Dakar en 2010 », le refus brut disait « période
couverte : 2023 à 2023 » — vrai du recensement seul, et laissant croire
qu'une autre série aurait peut-être la réponse. Il dit maintenant que les
projections ne remontent pas avant 2016, et l'utilisateur sait qu'il n'y a
rien à chercher ailleurs.

Voir equivalences.py pour la table et pour la raison qui fait de ce relais
une nécessité et non un choix fait à la place de l'utilisateur.


LES TROUS DANS UNE SÉRIE TEMPORELLE

Constaté sur « Comment le chômage a-t-il évolué entre 2015 et 2025 ? » :
la courbe rendait dix points, sautait 2020, et ne le disait pas. Le
segment tracé entre 2019 et 2021 n'était pas une mesure, mais il se
lisait comme telle — et sur l'année du Covid, l'erreur d'interprétation
est exactement celle qu'un lecteur ferait.

La note existante ne pouvait pas le voir. Elle compare le nombre de
points obtenus au nombre de périodes demandées, or `_intervalle` ne
retient que des périodes EXISTANTES : une année absente du catalogue
n'entre jamais dans l'intervalle, les deux comptes restent égaux, et le
trou passe.

Le trou ne se mesure donc pas par rapport à ce qui existe, mais par
rapport à la CADENCE que la série se donne à elle-même : `_trous()`
déduit le pas de l'écart minimal observé entre deux points, reconstruit
la grille attendue, et nomme ce qui manque.

Reste à ne pas confondre deux faits de nature différente :

    une série régulière à trou      annuelle, 2020 manquante
                                    -> le trou est une anomalie, on le nomme

    une série irrégulière           onze enquêtes entre 1997 et 2023
                                    -> l'écart est la nature de la série,
                                       et `avertissements.py` le dit déjà

La frontière est quantitative, donc vérifiable : si plus d'un quart des
points attendus manquent, la cadence déduite ne décrit pas la série, et
rien n'est conclu. Mesuré sur le catalogue — chômage annuel 2015-2025
avec 2020 manquante : 9 % de points absents, nommé ; `indice_bienetre`,
onze points sur vingt-sept : 59 %, écarté ; `taux_natalite`, dix-sept
points sur trente-quatre : 50 %, écarté.
"""

import re
from decimal import Decimal

from geography.models import Niveau, Zone

from .donnees import (
    ORDRE,
    get_indicateur,
    periodes_disponibles,
    situer,
    valeur,
    valeurs_par_zone,
    verifier_dimensions,
    verifier_granularite,
    zone_par_nom,
)

from .donnees import (
    ORDRE,
    _valeur_directe,
    get_indicateur,
    modalites,
    periodes_disponibles,
    situer,
    valeur,
    valeurs_par_zone,
    verifier_dimensions,
    verifier_granularite,
    zone_par_nom,
)
from .avertissements import avertissements_pour
from .equivalences import serie_equivalente
from .resultats import AnalysisResult, ErreurAnalyse, source_de
from .repartition import repartition  # noqa: E402

TOP_N_DEFAUT = 10
MAX_LIGNES = 60

# Au-delà de cette proportion de points absents, la cadence déduite ne
# décrit pas la série : c'est une série irrégulière, pas une série à trous.
PROPORTION_TROUS_MAX = 0.25

# Nombre de périodes nommées dans une note avant de couper.
TROUS_NOMMES_MAX = 6

# Motifs pour lesquels une série équivalente mérite d'être essayée : dans
# les trois cas, la demande est recevable et c'est la couverture de la
# série qui fait défaut.
MOTIFS_RELAYABLES = {
    "periode_non_couverte",
    "serie_trop_courte",
    "indicateur_vide",
}

RE_ANNEE = re.compile(r"^(\d{4})$")
RE_TRIMESTRE = re.compile(r"^(\d{4})-Q([1-4])$")


# --- outils communs --------------------------------------------------------

def _periode(ind, plan):
    """
    Résout la période demandée, ou prend la plus récente disponible.

    « actuel », « aujourd'hui » ou l'absence de période renvoient au
    dernier point publié — jamais à la date du jour, qui n'a pas de
    correspondance dans les données.
    """
    dispo = periodes_disponibles(ind)
    if not dispo:
        raise ErreurAnalyse(
            f"Aucune donnée chargée pour « {ind.libelle} ».",
            motif="indicateur_vide",
        )

    p = (plan.get("periode") or {})

    fin = p.get("fin")
    # Une valeur à une date ne demande qu'une année. Si la seule année
    # citée est arrivée dans `debut` (« dès 2015 »), c'est elle qui est
    # demandée, pas la dernière disponible.
    if fin in (None, "", "actuel", "dernier") \
            and _est_une_periode(p.get("debut")):
        fin = p.get("debut")
    if fin in (None, "", "actuel", "dernier"):
        return dispo[-1]

    fin = str(fin)
    if fin in dispo:
        return fin

    raise ErreurAnalyse(
        f"« {ind.libelle} » n'est pas disponible pour {fin}. "
        f"Période couverte : {dispo[0]} à {dispo[-1]}.",
        motif="periode_non_couverte",
        alternatives=[f"{ind.libelle} en {dispo[-1]}"],
    )


def _intervalle(ind, plan):
    """Sous-ensemble des périodes disponibles couvert par le plan."""
    dispo = periodes_disponibles(ind)
    if not dispo:
        raise ErreurAnalyse(
            f"Aucune donnée chargée pour « {ind.libelle} ».",
            motif="indicateur_vide",
        )
    p = (plan.get("periode") or {})
    debut = str(p.get("debut") or dispo[0])
    fin = str(p.get("fin") or dispo[-1])
    # Le tri lexicographique de « 2023 » et « 2026-Q1 » est chronologique.
    retenues = [x for x in dispo if debut <= x <= fin]
    return retenues or dispo


def _rang(periode):
    """
    (nature, rang) d'une période, ou (None, None) si le format est inconnu.

    Le rang est un entier sur lequel l'arithmétique est exacte : l'année
    elle-même pour une série annuelle, le numéro absolu du trimestre pour
    une série trimestrielle. Il permet de raisonner sur les écarts sans
    manipuler de dates, dont la plateforme n'a pas besoin.

    Un format inconnu ne provoque jamais d'erreur : il fait seulement
    renoncer au contrôle. Mieux vaut une note absente qu'une note fausse.
    """
    texte = str(periode or "")

    m = RE_ANNEE.match(texte)
    if m:
        return "annee", int(m.group(1))

    m = RE_TRIMESTRE.match(texte)
    if m:
        return "trimestre", int(m.group(1)) * 4 + int(m.group(2)) - 1

    return None, None


def _periode_du_rang(nature, rang):
    """Opération inverse de `_rang`, pour nommer un trou dans la série."""
    if nature == "annee":
        return str(rang)
    return f"{rang // 4}-Q{rang % 4 + 1}"


def _est_une_periode(valeur_brute):
    """Une valeur de plan est-elle une période, et non « actuel » ?"""
    return _rang(valeur_brute)[0] is not None


def _trous(periodes):
    """
    Périodes absentes d'une série qui devrait être régulière.

    Le pas est celui que la série se donne : l'écart minimal observé entre
    deux points consécutifs. La grille attendue en découle, et ce qui n'y
    figure pas est un trou.

    Retourne une liste vide dès qu'il y a un doute — format inconnu,
    natures mélangées, moins de trois points, ou série trop irrégulière
    pour qu'une cadence ait un sens. Cette fonction ne sert qu'à produire
    une note : son silence est sans conséquence, une note fausse ne
    l'aurait pas été.
    """
    rangs, natures = [], set()
    for p in periodes:
        nature, rang = _rang(p)
        if nature is None:
            return []
        natures.add(nature)
        rangs.append(rang)

    # Deux points ne révèlent aucune cadence : l'écart qui les sépare est
    # le pas par construction, et la grille n'a pas de trou.
    if len(natures) != 1 or len(rangs) < 3:
        return []

    nature = natures.pop()
    rangs = sorted(set(rangs))
    pas = min(b - a for a, b in zip(rangs, rangs[1:]))
    if pas <= 0:
        return []

    attendus = list(range(rangs[0], rangs[-1] + 1, pas))
    presents = set(rangs)
    manquants = [r for r in attendus if r not in presents]

    if not manquants:
        return []
    if len(manquants) / len(attendus) > PROPORTION_TROUS_MAX:
        return []

    return [_periode_du_rang(nature, r) for r in manquants]


def _enumerer(periodes):
    """Liste lisible, coupée au-delà de `TROUS_NOMMES_MAX`."""
    if len(periodes) <= TROUS_NOMMES_MAX:
        return ", ".join(periodes)
    return ", ".join(periodes[:TROUS_NOMMES_MAX]) + "…"


def _prepare(plan):
    """Validation commune à toutes les méthodes."""
    ind = get_indicateur(plan.get("indicateur"))
    filtres = plan.get("filtres") or {}
    verifier_dimensions(ind, filtres)
    verifier_granularite(ind, plan.get("niveau"))
    return ind, filtres


def _note_agregation(ind, niveau):
    """Signale une somme de descendants, pour que le chiffre soit lisible."""
    if niveau and ind.agregeable and niveau != ind.granularite_geo_min:
        return (f"Valeur obtenue par agrégation des niveaux inférieurs "
                f"({ind.granularite_geo_min}).")
    return None


# --- 1. valeur simple ------------------------------------------------------

def valeur_simple(plan):
    ind, filtres = _prepare(plan)
    periode = _periode(ind, plan)

    noms = plan.get("zones") or []
    if not noms:
        raise ErreurAnalyse(
            "Aucune zone précisée.", motif="zone_manquante",
            alternatives=["préciser une région, un département ou le Sénégal"],
        )

    niveau_zone = plan.get("niveau_zone")
    if niveau_zone:
        verifier_granularite(ind, niveau_zone)
    zone = zone_par_nom(noms[0], niveau=niveau_zone)
    v = valeur(ind, zone, periode, filtres)

    if v is None:
        raise ErreurAnalyse(
            f"Pas de donnée pour « {ind.libelle} » à {zone.nom} "
            f"en {periode}.",
            motif="donnee_absente",
        )

    notes = []
    if zone.niveau == Niveau.QUARTIER:
        notes.append(f"Localité recensée comme quartier, village ou "
                     f"hameau : {situer(zone)}.")

    # La note ne vaut que si la valeur a réellement été sommée : le total
    # national des projections est publié tel quel.
    if not isinstance(filtres.get("age"), list) \
            and _valeur_directe(ind, zone, periode, filtres) is None:
        n = _note_agregation(ind, zone.niveau)
        if n:
            notes.append(n)

    if ind.prix_base:
        notes.append(f"Valeurs en prix {ind.prix_base}.")

    return AnalysisResult(
        lignes=[{"zone": zone.nom, "code": zone.code,
                 "geojson_id": zone.geojson_id,
                 "periode": periode, "valeur": v}],
        unite=ind.unite,
        sources=[source_de(ind)],
        chart_hint="kpi",
        notes=notes,
        meta={"indicateur": ind.libelle, "periode": periode,
              "zone": zone.nom, "filtres": filtres},
    )


# --- 2. classement ---------------------------------------------------------

def classement(plan):
    ind, filtres = _prepare(plan)
    periode = _periode(ind, plan)

    niveau = plan.get("niveau") or Niveau.REGION
    parent = None
    if plan.get("zones"):
        candidat = zone_par_nom(plan["zones"][0])
        # Une zone citée avec un niveau plus fin sert de périmètre :
        # « les quartiers de Dakar » -> parent = Dakar.
        if candidat.niveau in ORDRE and niveau in ORDRE \
                and ORDRE.index(niveau) > ORDRE.index(candidat.niveau):
            parent = candidat

    qs = Zone.objects.filter(niveau=niveau)
    if parent is not None:
        qs = qs.filter(code__startswith=f"{parent.code}-")

    lignes, manquantes = valeurs_par_zone(ind, list(qs), periode, filtres)
    if not lignes:
        raise ErreurAnalyse(
            f"Aucune donnée pour « {ind.libelle} » au niveau {niveau} "
            f"en {periode}.",
            motif="donnee_absente",
        )

    desc = (plan.get("ordre") or "desc") == "desc"
    lignes.sort(key=lambda l: l["valeur"], reverse=desc)

    n = plan.get("top_n") or TOP_N_DEFAUT
    lignes = lignes[:min(int(n), MAX_LIGNES)]

    notes = []
    if manquantes:
        notes.append(f"{len(manquantes)} zone(s) sans donnée, exclues du "
                     f"classement : {', '.join(sorted(manquantes)[:5])}"
                     + ("…" if len(manquantes) > 5 else ""))
    note = _note_agregation(ind, niveau)
    if note:
        notes.append(note)
    if not ind.agregeable:
        notes.append("Indicateur non agrégeable : les valeurs affichées "
                     "sont celles publiées pour chaque zone, sans cumul.")

    return AnalysisResult(
        lignes=lignes,
        unite=ind.unite,
        sources=[source_de(ind)],
        chart_hint="bar",
        notes=notes,
        meta={"indicateur": ind.libelle, "periode": periode,
              "niveau": niveau, "ordre": "desc" if desc else "asc",
              "perimetre": parent.nom if parent else "Sénégal",
              "filtres": filtres,
              "unique": bool(plan.get("reponse_unique")),
            },
    )


# --- 3. évolution ----------------------------------------------------------

def _est_un_taux(unite):
    """%, ‰, « pour 1000 » : un écart se lit en points, pas en %."""
    u = (unite or "").strip().lower()
    return "%" in u or "‰" in u or u.startswith("pour 1")


def _ecart_annees(p1, p2):
    """Durée réelle en années entre deux périodes, ou None."""
    n1, r1 = _rang(p1)
    n2, r2 = _rang(p2)
    if n1 is None or n1 != n2:
        return None
    return (r2 - r1) / (4 if n1 == "trimestre" else 1)


def _variations(serie, unite, glissement):
    """
    Variations calculées sur la durée RÉELLE de la courbe.

    L'ancienne version comparait le dernier point à l'avant-dernier sous
    le libellé « sur la période », et divisait la croissance annuelle par
    le nombre de points au lieu du nombre d'années.
    """
    premier, dernier = serie[0], serie[-1]
    v0, v1 = Decimal(premier["valeur"]), Decimal(dernier["valeur"])
    taux = _est_un_taux(unite)
    annees = _ecart_annees(premier["periode"], dernier["periode"])

    out = {"est_taux": taux, "annees": annees,
           "variation_absolue": v1 - v0, "variation_pct": None,
           "tcam_pct": None, "glissement_pct": None}

    if not taux and v0:
        out["variation_pct"] = (v1 - v0) / v0 * 100
    if not taux and v0 > 0 and v1 > 0 and annees and annees >= 1:
        exposant = Decimal(1) / Decimal(str(annees))
        out["tcam_pct"] = ((v1 / v0) ** exposant - 1) * 100

    # Glissement annuel : même trimestre un an plus tôt, cherché par sa
    # date et non par sa position dans la liste.
    if glissement:
        nature, rang = _rang(dernier["periode"])
        if nature == "trimestre":
            cible = _periode_du_rang(nature, rang - 4)
            avant = next((l for l in serie if l["periode"] == cible), None)
            if avant and avant["valeur"]:
                va = Decimal(avant["valeur"])
                out["glissement_pct"] = (v1 - va) / va * 100
    return out


def evolution(plan):
    ind, filtres = _prepare(plan)
    periodes = _intervalle(ind, plan)

    noms = plan.get("zones") or []
    zone = zone_par_nom(noms[0]) if noms else \
        Zone.objects.filter(niveau=Niveau.NATIONAL).first()
    if zone is None:
        raise ErreurAnalyse("Aucune zone précisée.", motif="zone_manquante")

    serie = []
    for p in periodes:
        v = valeur(ind, zone, p, filtres)
        if v is not None:
            serie.append({"periode": p, "valeur": v})

    if len(serie) < 2:
        raise ErreurAnalyse(
            f"« {ind.libelle} » ne comporte pas assez de points pour "
            f"{zone.nom} : une évolution demande au moins deux périodes.",
            motif="serie_trop_courte",
        )

    notes = []

    if len(noms) > 1:
        notes.append(f"Plusieurs zones citées : la courbe porte sur "
                     f"{zone.nom} seulement.")

    # La période demandée peut précéder le début de la série, ou dépasser sa
    # fin. Le dire, plutôt que de laisser croire que la courbe couvre ce qui
    # a été demandé : une courbe qui commence silencieusement neuf ans trop
    # tard est un mensonge par omission.
    #
    # Le contrôle de format n'est pas décoratif : `fin` peut valoir
    # « actuel », et la comparaison de chaînes placerait « actuel » après
    # « 2025 », produisant une note sur une période qui n'en est pas une.
    p = (plan.get("periode") or {})
    debut_demande, fin_demandee = p.get("debut"), p.get("fin")

    if _est_une_periode(debut_demande) \
            and str(debut_demande) < serie[0]["periode"]:
        notes.append(f"Période demandée à partir de {debut_demande} ; la "
                     f"série commence en {serie[0]['periode']}.")

    if _est_une_periode(fin_demandee) \
            and str(fin_demandee) > serie[-1]["periode"]:
        notes.append(f"Période demandée jusqu'à {fin_demandee} ; la série "
                     f"s'arrête en {serie[-1]['periode']}.")

    # Périodes présentes au catalogue mais sans valeur pour CETTE zone :
    # l'information est plus précise que celle d'un trou, puisque d'autres
    # zones ont la donnée.
    obtenues = {l["periode"] for l in serie}
    absentes = [x for x in periodes if x not in obtenues]
    if absentes:
        notes.append(f"{len(absentes)} période(s) de l'intervalle sans "
                     f"donnée pour {zone.nom}, omises de la courbe : "
                     f"{_enumerer(absentes)}.")

    # Trous de la série elle-même : l'année manque pour toutes les zones et
    # n'est donc pas dans l'intervalle. Les périodes déjà signalées
    # ci-dessus sont retirées, pour ne pas dire deux fois la même chose.
    trous = [t for t in _trous([l["periode"] for l in serie])
             if t not in absentes]
    if trous:
        if len(trous) == 1:
            notes.append(f"Aucune donnée pour {trous[0]} : la courbe relie "
                         f"directement les deux points voisins, et ce "
                         f"segment ne correspond à aucune mesure.")
        else:
            notes.append(f"Aucune donnée pour {len(trous)} périodes de "
                         f"l'intervalle ({_enumerer(trous)}) : la courbe "
                         f"relie directement les points voisins, et ces "
                         f"segments ne correspondent à aucune mesure.")

    # RÈGLE DE SAISONNALITÉ.
    # Sur une série trimestrielle, comparer un trimestre au précédent
    # confond le cycle saisonnier avec une tendance : la valeur ajoutée
    # du secteur primaire chute chaque premier trimestre à cause du cycle
    # des récoltes, sans qu'aucun effondrement ne se produise. On compare
    # donc toujours au même trimestre de l'année précédente.

    glissement = ind.comparaison_defaut == "t-4"
    if glissement:
        notes.append("Comparaison effectuée en glissement annuel "
                     "(trimestre T comparé au trimestre T-4), en raison "
                     "de la saisonnalité de cette série.")

    variations = _variations(serie, ind.unite, glissement)
    note = _note_agregation(ind, zone.niveau)
    if note:
        notes.append(note)
    if ind.prix_base:
        notes.append(f"Valeurs en prix {ind.prix_base}.")

    return AnalysisResult(
        lignes=serie,
        unite=ind.unite,
        sources=[source_de(ind)],
        chart_hint="line",
        notes=notes,
        meta={
            "indicateur": ind.libelle, "zone": zone.nom,
            "debut": serie[0]["periode"], "fin": serie[-1]["periode"],
            "points": len(serie),
            "periodes_absentes": absentes,
            "trous": trous,
            "base_comparaison": "t-4" if glissement else "periode",
            **variations,
            "filtres": filtres,
        },
    )


# --- 4. cartographie -------------------------------------------------------

def geographique(plan):
    ind, filtres = _prepare(plan)
    periode = _periode(ind, plan)

    # La carte est dessinée à partir de sn.json, qui ne contient que les
    # contours régionaux : on ramène donc toute demande à ce niveau.
    niveau = plan.get("niveau") or Niveau.REGION
    notes = []
    if niveau != Niveau.REGION:
        notes.append("Cartographie disponible au niveau régional ; "
                     "les valeurs sont agrégées à ce niveau.")
        niveau = Niveau.REGION

    zones = list(Zone.objects.filter(niveau=niveau))
    lignes, manquantes = valeurs_par_zone(ind, zones, periode, filtres)

    if not lignes:
        raise ErreurAnalyse(
            f"Aucune donnée cartographiable pour « {ind.libelle} » "
            f"en {periode}.",
            motif="donnee_absente",
        )

    sans_code = [l["zone"] for l in lignes if not l["geojson_id"]]
    if sans_code:
        notes.append(f"{len(sans_code)} zone(s) sans contour "
                     f"cartographique : {', '.join(sans_code[:5])}.")
    if manquantes:
        notes.append(f"{len(manquantes)} région(s) sans donnée, affichées "
                     f"en gris : {', '.join(sorted(manquantes)[:5])}"
                     + ("…" if len(manquantes) > 5 else ""))

    note = _note_agregation(ind, niveau)
    if note:
        notes.append(note)

    valeurs = [l["valeur"] for l in lignes]
    return AnalysisResult(
        lignes=sorted(lignes, key=lambda l: l["valeur"], reverse=True),
        unite=ind.unite,
        sources=[source_de(ind)],
        chart_hint="choropleth",
        notes=notes,
        meta={"indicateur": ind.libelle, "periode": periode,
              "niveau": niveau, "min": min(valeurs), "max": max(valeurs),
              "couvertes": len(lignes), "filtres": filtres},
    )

# --- 5. comparaison --------------------------------------------------------

LIBELLES_SEXE = {"H": "Hommes", "M": "Hommes", "F": "Femmes"}


def _fr(x, decimales=0):
    return (f"{Decimal(x):,.{decimales}f}"
            .replace(",", " ").replace(".", ","))


def comparaison(plan):
    """
    Plusieurs zones, ou les deux sexes, côte à côte, à la même période.
    Chaque valeur est calculée comme une valeur simple ; l'écart et le
    rapport le sont ici, en Decimal.
    """
    ind, filtres = _prepare(plan)
    periode = _periode(ind, plan)

    niveau = plan.get("niveau_zone")
    if niveau:
        verifier_granularite(ind, niveau)
    zones = [zone_par_nom(n, niveau=niveau)
             for n in (plan.get("zones") or ["SENEGAL"])]

    sexes = [None]
    if plan.get("dimension") == "sexe":
        filtres = {k: v for k, v in filtres.items() if k != "sexe"}
        sexes = modalites(ind, "sexe") or [None]

    lignes, manquantes = [], []
    for z in zones:
        for s in sexes:
            f = {**filtres, "sexe": s} if s else filtres
            nom = f"{z.nom} · {LIBELLES_SEXE.get(s, s)}" if s else z.nom
            v = valeur(ind, z, periode, f)
            if v is None:
                manquantes.append(nom)
                continue
            lignes.append({"zone": nom, "code": z.code,
                           "geojson_id": z.geojson_id,
                           "periode": periode, "valeur": v})

    if len(lignes) < 2:
        raise ErreurAnalyse(
            f"Pas assez de données pour comparer « {ind.libelle} » en "
            f"{periode} : {', '.join(manquantes) or 'aucune zone'} sans "
            f"valeur.", motif="donnee_absente")

    if plan.get("dimension") == "sexe":
        # Lignes gardées dans l'ordre des zones (Dakar H, Dakar F, Thiès…) :
        # l'écart utile est DANS chaque zone, pas entre Dakar · Hommes et
        # Thiès · Femmes.
        notes = []
        for z in zones:
            parts = {l["zone"].split(" · ")[-1]: Decimal(l["valeur"])
                     for l in lignes if l["code"] == z.code}
            h, f = parts.get("Hommes"), parts.get("Femmes")
            if h is not None and f:
                d = h - f
                plus = (f"{_fr(d)} hommes de plus que de femmes" if d >= 0
                        else f"{_fr(-d)} femmes de plus que d'hommes")
                notes.append(f"{z.nom} : {plus} "
                             f"({_fr(h / f * 100, 2)} hommes pour 100 femmes).")
        ecart = None
    else:
        lignes.sort(key=lambda l: l["valeur"], reverse=True)
        haut, bas = lignes[0], lignes[-1]
        v_haut, v_bas = Decimal(haut["valeur"]), Decimal(bas["valeur"])
        ecart = v_haut - v_bas
        if _est_un_taux(ind.unite):
            note = (f"Écart entre {haut['zone']} et {bas['zone']} : "
                    f"{_fr(ecart, 1)} points.")
        else:
            note = (f"Écart entre {haut['zone']} et {bas['zone']} : "
                    f"{_fr(ecart, 0 if ind.agregeable else 2)} {ind.unite}")
            note += (f", soit {_fr(v_haut / v_bas, 2)} fois plus."
                     if ind.agregeable and v_bas > 0 else ".")
        notes = [note]
    if manquantes:
        notes.append(f"Sans donnée, donc absentes de la comparaison : "
                     f"{', '.join(manquantes)}.")
    if ind.prix_base:
        notes.append(f"Valeurs en prix {ind.prix_base}.")

    return AnalysisResult(
        lignes=lignes,
        unite=ind.unite,
        sources=[source_de(ind)],
        chart_hint="bar",
        notes=notes,
        meta={"indicateur": ind.libelle, "periode": periode,
              "zones": [z.nom for z in zones], "ecart": ecart,
              "filtres": filtres, "dimension": plan.get("dimension")},
    )


# --- dispatcher ------------------------------------------------------------

METHODES = {
    "valeur_simple": valeur_simple,
    "classement": classement,
    "evolution": evolution,
    "geographique": geographique,
    "repartition": repartition,
    "comparaison": comparaison,
}


# --- relais entre séries équivalentes --------------------------------------

def _niveau_compatible(niveau, ind):
    """
    Ramène le niveau demandé à celui que l'indicateur publie, s'il est plus
    fin.

    ORDRE va du plus large au plus fin : un indice supérieur à celui de la
    granularité publiée désigne une demande que l'indicateur ne peut pas
    servir. Même raisonnement que le plafonnement fait en amont — le moteur
    sait agréger, il ne sait pas désagréger — appliqué ici au remplaçant,
    qui n'a pas la même granularité que l'indicateur d'origine.
    """
    if not niveau or niveau not in ORDRE:
        return niveau
    publie = ind.granularite_geo_min
    if publie not in ORDRE:
        return niveau
    if ORDRE.index(niveau) > ORDRE.index(publie):
        return publie
    return niveau


def _plan_relais(plan, remplacant):
    """Le même plan, servi par la série de relais."""
    return {
        **plan,
        "indicateur": remplacant.code,
        "niveau": _niveau_compatible(plan.get("niveau"), remplacant),
    }


def _annoter_avertissements(resultat, code, plan):
    """
    Ajoute les limites méthodologiques des données employées.

    Placé dans `executer()` plutôt que dans chaque méthode : les cinq
    méthodes y passent, et une sixième en bénéficiera sans qu'on y pense.

    Les notes vont en FIN de liste. Celles produites par la méthode —
    agrégation, glissement annuel, zones manquantes — décrivent ce calcul-ci
    et viennent d'abord ; les limites des données valent pour toute question
    posée à cette série.
    """
    for note in avertissements_pour(
        code,
        methode=plan.get("methode"),
        dimension=plan.get("dimension"),
        filtres=plan.get("filtres"),
    ):
        if note not in resultat.notes:
            resultat.notes.append(note)
    return resultat


def _annoter_relais(resultat, plan, premiere, remplacant):
    """
    Inscrit le relais dans le résultat.

    La note vient en tête : c'est la première chose à savoir sur ce
    résultat. Le message d'origine y figure mot pour mot, pour que
    l'utilisateur sache ce que la série demandée ne pouvait pas faire.
    """
    resultat.notes.insert(
        0,
        f"Série relayée. {premiere.message} Le résultat ci-dessus provient "
        f"de « {remplacant.libelle} », déclarée au catalogue comme série "
        f"équivalente.",
    )
    resultat.meta["serie_demandee"] = plan.get("indicateur")
    resultat.meta["serie_relais"] = remplacant.code
    resultat.meta["motif_relais"] = premiere.motif

    # Les avertissements portent sur la série qui a RÉPONDU, pas sur celle
    # qui était demandée : c'est de ses limites que le lecteur a besoin.
    return _annoter_avertissements(resultat, remplacant.code, plan)


def _refus_complete(premiere, remplacant, seconde):
    """
    Le refus d'origine, complété par ce que la série de relais ne pouvait
    pas faire non plus.

    Le motif reste celui d'origine : c'est la demande de l'utilisateur qui
    n'aboutit pas, et le détour tenté pour y répondre ne doit pas changer
    la nature du refus. Seul le message gagne en précision.

    Sans ce complément, « la population de Dakar en 2010 » répondait
    « période couverte : 2023 à 2023 » — exact pour le recensement, et
    laissant croire qu'une autre série pourrait avoir la réponse.
    """
    if seconde.motif == "granularite_indisponible":
        detail = (f"La série équivalente « {remplacant.libelle} » ne descend "
                  f"pas sous le niveau {remplacant.granularite_geo_min} et ne "
                  f"peut donc pas répondre non plus.")
    else:
        couverture = periodes_disponibles(remplacant)
        etendue = (f" (couverture : {couverture[0]} à {couverture[-1]})"
                   if couverture else "")
        detail = (f"La série équivalente « {remplacant.libelle} »{etendue} ne "
                  f"peut pas répondre non plus.")

    alternatives = list(premiere.alternatives)
    couverture = periodes_disponibles(remplacant)
    if couverture:
        propose = f"{remplacant.libelle} en {couverture[-1]}"
        if propose not in alternatives:
            alternatives.append(propose)

    return ErreurAnalyse(
        f"{premiere.message} {detail}",
        motif=premiere.motif,
        alternatives=alternatives,
    )


def executer(plan):
    """
    Point d'entrée unique du moteur.

    Le plan a déjà été validé quant à sa forme ; ce qui est vérifié ici
    relève des données elles-mêmes — existence de l'indicateur,
    ventilations autorisées, granularité et période disponibles.

    Une seule seconde tentative, et seulement sur les motifs où l'échec
    vient de la couverture de la série. Au-delà, le refus d'origine est
    la réponse.
    """
    methode = plan.get("methode")
    fn = METHODES.get(methode)
    if fn is None:
        raise ErreurAnalyse(
            f"Méthode « {methode} » non disponible.",
            motif="methode_inconnue",
            alternatives=sorted(METHODES),
        )

    try:
        resultat = fn(plan)
    except ErreurAnalyse as premiere:
        if premiere.motif not in MOTIFS_RELAYABLES:
            raise

        remplacant = serie_equivalente(plan.get("indicateur"))
        if remplacant is None:
            raise

        try:
            resultat = fn(_plan_relais(plan, remplacant))
        except ErreurAnalyse as seconde:
            # `from None` : la chaîne d'exceptions internes n'apprend rien à
            # l'utilisateur, et le refus rendu doit rester celui de sa
            # demande.
            raise _refus_complete(premiere, remplacant, seconde) from None

        return _annoter_relais(resultat, plan, premiere, remplacant)

    return _annoter_avertissements(resultat, plan.get("indicateur"), plan)