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
"""

from decimal import Decimal

from geography.models import Niveau, Zone

from .donnees import (
    ORDRE,
    get_indicateur,
    periodes_disponibles,
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

# Motifs pour lesquels une série équivalente mérite d'être essayée : dans
# les trois cas, la demande est recevable et c'est la couverture de la
# série qui fait défaut.
MOTIFS_RELAYABLES = {
    "periode_non_couverte",
    "serie_trop_courte",
    "indicateur_vide",
}


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

    zone = zone_par_nom(noms[0])
    v = valeur(ind, zone, periode, filtres)

    if v is None:
        raise ErreurAnalyse(
            f"Pas de donnée pour « {ind.libelle} » à {zone.nom} "
            f"en {periode}.",
            motif="donnee_absente",
        )

    notes = []
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
              "filtres": filtres},
    )


# --- 3. évolution ----------------------------------------------------------

def _variation(serie, pas):
    """
    Variation entre le dernier point et celui situé `pas` rangs avant.

    `pas` vaut 4 pour une série trimestrielle (glissement annuel) et 1
    pour une série annuelle.
    """
    if len(serie) <= pas:
        return None, None
    avant, apres = serie[-1 - pas]["valeur"], serie[-1]["valeur"]
    if not avant:
        return None, None
    ecart = Decimal(apres) - Decimal(avant)
    return ecart, ecart / Decimal(avant) * 100


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

    # La période demandée peut précéder le début de la série. Le dire, plutôt
    # que de laisser croire que la courbe couvre ce qui a été demandé : une
    # courbe qui commence silencieusement neuf ans trop tard est un
    # mensonge par omission.
    demande = (plan.get("periode") or {}).get("debut")
    if demande and str(demande) < serie[0]["periode"]:
        notes.append(f"Période demandée à partir de {demande} ; la série "
                     f"commence en {serie[0]['periode']}.")

    # RÈGLE DE SAISONNALITÉ.
    # Sur une série trimestrielle, comparer un trimestre au précédent
    # confond le cycle saisonnier avec une tendance : la valeur ajoutée
    # du secteur primaire chute chaque premier trimestre à cause du cycle
    # des récoltes, sans qu'aucun effondrement ne se produise. On compare
    # donc toujours au même trimestre de l'année précédente.
    pas = 4 if ind.comparaison_defaut == "t-4" else 1
    if pas == 4:
        notes.append("Comparaison effectuée en glissement annuel "
                     "(trimestre T comparé au trimestre T-4), en raison "
                     "de la saisonnalité de cette série.")

    ecart, pct = _variation(serie, pas)

    # Taux de croissance annuel moyen, sur la durée réellement couverte.
    debut, fin = Decimal(serie[0]["valeur"]), Decimal(serie[-1]["valeur"])
    annees = max(len(serie) - 1, 1) / (4 if pas == 4 else 1)
    tcam = None
    if debut > 0 and fin > 0 and annees >= 1:
        tcam = ((fin / debut) ** Decimal(1 / annees) - 1) * 100

    note = _note_agregation(ind, zone.niveau)
    if note:
        notes.append(note)
    if ind.prix_base:
        notes.append(f"Valeurs en prix {ind.prix_base}.")
    if len(serie) < len(periodes):
        notes.append(f"{len(periodes) - len(serie)} période(s) sans donnée, "
                     f"omises de la courbe.")

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
            "variation_absolue": ecart,
            "variation_pct": pct,
            "tcam_pct": tcam,
            "base_comparaison": "t-4" if pas == 4 else "n-1",
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


# --- dispatcher ------------------------------------------------------------

METHODES = {
    "valeur_simple": valeur_simple,
    "classement": classement,
    "evolution": evolution,
    "geographique": geographique,
    "repartition": repartition,
    # "comparaison": comparaison,     ← phase 2
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