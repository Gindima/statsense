"""
backend/ai/documentaire.py

StatSense AI — Questions sur les données, et non sur des valeurs

Certaines questions ne demandent pas un chiffre. « Quand a eu lieu le
dernier recensement ? », « Qui a réalisé le RGPH-5 ? », « Quelle est la
source de ces données ? » portent sur les métadonnées.

Pourquoi il faut les reconnaître AVANT d'appeler le modèle :

    « Quand a eu lieu le dernier recensement ? »
        -> valeur_simple · pop_totale · SENEGAL
        -> SENEGAL 18 126 342 personnes

Le modèle, sommé de choisir un indicateur, en choisit un. La chaîne
calcule, et rend un effectif à qui demandait une date. C'est le pire mode
de défaillance de la plateforme : une réponse fausse, complète et
confiante, sans aucun signe que la question n'a pas été comprise. Un refus
aurait été préférable ; une vraie réponse l'est davantage.

Ces formulations sont une liste fermée — « quand a eu lieu », « qui a
réalisé », « qu'est-ce que », « quelle est la source », « quelle est la
différence entre » — donc du ressort du code. Les détecter en amont évite
aussi l'appel au modèle, soit vingt-cinq secondes.


RIEN N'EST INVENTÉ ICI

Chaque réponse est construite à partir de ce que la base contient déjà :
les libellés et granularités du catalogue, les plages de périodes
calculées sur les observations, les sources avec leur URL et leur date
d'extraction. Aucune phrase de culture générale, aucune date mémorisée.

Quand une question documentaire est reconnue mais que la base ne porte pas
la réponse — la définition statistique du chômage, par exemple — on le dit
et on renvoie vers l'indicateur correspondant. C'est la même règle que
pour les valeurs : mieux vaut une limite énoncée qu'une réponse plausible.
"""

import re
import unicodedata

# Chaque entrée : (nom du traitement, formulations qui le déclenchent).
# Les formulations sont ancrées et spécifiques — une liste large
# avalerait des questions statistiques légitimes. « Quand le chômage a-t-il
# augmenté ? » commence par « quand » et n'est pas documentaire.
MOTIFS = [
    ("difference_series", (
        "difference entre population recensee et population projetee",
        "difference entre la population recensee et la population projetee",
        "difference entre le recensement et les projections",
        "difference entre population recensee",
        "recensee et projetee",
        "recensement et projection",
        "pourquoi deux populations",
        "pourquoi deux chiffres de population",
        "donnees du rgph 5 et celles", "rgph 5 et le catalogue",
    )),
    ("recensement", (
        "quand a eu lieu le dernier recensement",
        "quand a eu lieu le recensement",
        "date du dernier recensement",
        "date du recensement",
        "quand le recensement a eu lieu",
        "quand a t il eu lieu le recensement",
        "en quelle annee le recensement",
        "qui a realise le rgph",
        "qui a realise le recensement",
        "qui a produit ces donnees",
        "comment fonctionne le recensement",
        "comment se deroule le recensement",
    )),
    ("producteur", (
        "qu est ce que l ansd",
        "c est quoi l ansd",
        "que fait l ansd",
        "qui est l ansd",
        "que signifie ansd",
    )),
    ("sources", (
        "quelle est la source de ces donnees",
        "quelles sont les sources",
        "quelle est la source",
        "d ou viennent ces donnees",
        "d ou proviennent ces donnees",
        "quand les donnees ont elles ete publiees",
        "date de publication des donnees",
        "d ou provient", "d ou proviennent", "source officielle",
        "affiche les sources",
        "vos donnees sont elles fiables",
    )),
    ("definition", (
        "donne moi la definition",
        "quelle est la definition",
        "que veut dire le taux de chomage",
        "comment est calcule le taux de chomage",
        "comment calculez vous",
        "quelle formule", "comment as tu obtenu", "comment as tu calcule",
        "etapes de calcul", "utilises dans ton calcul",
        "que signifie le rapport de masculinite",
    )),
    ("inventaire", (
        "donne moi toutes les donnees disponibles",
        "quelles donnees avez vous",
        "quelles sont les donnees disponibles",
        "que savez vous faire",
        "quels indicateurs sont disponibles",
        "sur quelle periode les donnees", "sont elles disponibles",
        "quel niveau geographique", "combien d observations",
    )),
]


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _nature(question):
    """Nom du traitement documentaire applicable, ou None."""
    texte = _norm(question)
    for nature, formulations in MOTIFS:
        if any(f in texte for f in formulations):
            return nature
    return None


def _plages():
    """{code: (premiere, derniere)} pour les indicateurs qui ont des
    observations."""
    from observations.models import Observation
    out = {}
    lignes = (Observation.objects
              .values_list("indicateur__code", "periode").distinct())
    for code, periode in lignes:
        if code is None or periode is None:
            continue
        p = out.get(code)
        out[code] = (min(p[0], periode), max(p[1], periode)) if p \
            else (periode, periode)
    return out


def _indicateur(code):
    from catalog.models import Indicateur
    return Indicateur.objects.filter(code=code).select_related("source").first()


def _ligne_source(s):
    """« nom — plateforme, extraction du … », avec ce qui est renseigné."""
    if s is None:
        return None
    bouts = [getattr(s, "nom", None) or getattr(s, "code", "source")]
    plateforme = getattr(s, "plateforme", None)
    if plateforme:
        bouts.append(plateforme)
    date = getattr(s, "date_extraction", None)
    if date:
        bouts.append(f"extraction du {date}")
    return " — ".join(bouts[:1]) + (
        " (" + ", ".join(bouts[1:]) + ")" if len(bouts) > 1 else "")


def _difference_series():
    plages = _plages()
    recense = _indicateur("pop_totale")
    projete = _indicateur("pop_region")
    if recense is None or projete is None:
        return None, []

    def decrire(i):
        p = plages.get(i.code)
        periode = f"{p[0]} à {p[1]}" if p and p[0] != p[1] else (
            str(p[0]) if p else "période non renseignée")
        return (f"« {i.libelle} » : {periode}, jusqu'au niveau "
                f"{i.granularite_geo_min}")

    return (
        "Le catalogue porte deux séries de population, et elles ne mesurent "
        "pas la même chose.\n\n"
        f"· {decrire(recense)}. C'est un dénombrement : des personnes "
        "effectivement recensées sur le terrain.\n"
        f"· {decrire(projete)}. C'est une estimation calculée à partir du "
        "recensement et des taux de natalité, mortalité et migration.\n\n"
        "Leurs valeurs diffèrent donc normalement, et aucune des deux n'est "
        "fausse. Une question portant sur une année autre que celle du "
        "recensement est servie par les projections ; une question sur un "
        "quartier ou une commune n'est servie que par le recensement, seul "
        "publié à ce niveau.",
        ["pop_totale", "pop_region"],
    )


def _recensement():
    plages = _plages()
    i = _indicateur("pop_totale")
    if i is None:
        return None, []
    p = plages.get("pop_totale")
    annee = p[0] if p else None
    source = _ligne_source(getattr(i, "source", None))

    phrases = []
    if annee:
        phrases.append(
            f"Les données de recensement du catalogue portent l'année "
            f"{annee} : c'est le millésime du RGPH-5, cinquième recensement "
            f"général de la population et de l'habitat du Sénégal.")
    if source:
        phrases.append(f"Producteur et provenance : {source}.")
    phrases.append(
        "Je ne dispose pas du calendrier de l'opération ni de sa "
        "méthodologie de collecte — seulement des résultats publiés et de "
        "leur année de référence.")
    return "\n\n".join(phrases), ["pop_totale", "menages", "concessions"]


def _producteur():
    from catalog.models import Source
    noms = list(Source.objects.values_list("nom", flat=True))
    texte = (
        "L'ANSD est l'Agence Nationale de la Statistique et de la "
        "Démographie, producteur officiel de la statistique publique au "
        "Sénégal. Toutes les données de cette plateforme en proviennent ; "
        "aucune n'est produite ici.")
    if noms:
        texte += "\n\nJeux de données chargés :\n" + "\n".join(
            f"· {n}" for n in noms)
    return texte, []


def _sources():
    from catalog.models import Indicateur, Source
    lignes = []
    for s in Source.objects.all():
        detail = _ligne_source(s)
        codes = list(Indicateur.objects.filter(source=s)
                     .values_list("code", flat=True))
        if detail:
            lignes.append(f"· {detail} — {len(codes)} indicateur(s)")
    if not lignes:
        return None, []
    return (
        "Chaque chiffre rendu par la plateforme porte sa source, affichée "
        "sous le résultat. Les jeux chargés sont :\n\n" + "\n".join(lignes) +
        "\n\nTrois anomalies ont été relevées dans les fichiers d'origine "
        "au chargement : elles sont corrigées de façon documentée et "
        "nommées une par une dans le journal de chargement.",
        [],
    )


def _definition():
    return (
        "Je ne porte pas les définitions méthodologiques des indicateurs — "
        "seulement leurs valeurs, leurs unités, leurs ventilations et leur "
        "source. Pour la définition exacte d'un concept statistique, les "
        "notes méthodologiques de l'ANSD font autorité.\n\n"
        "Je peux en revanche vous donner la valeur de l'indicateur, sa "
        "plage de périodes et son niveau géographique le plus fin.",
        ["taux_chomage_a", "taux_emploi", "rapport_masculinite"],
    )


def _inventaire():
    from catalog.models import Indicateur
    plages = _plages()
    lignes = []
    for i in Indicateur.objects.order_by("code"):
        p = plages.get(i.code)
        periode = f"{p[0]}–{p[1]}" if p and p[0] != p[1] else (
            str(p[0]) if p else "dérivé")
        lignes.append(f"· {i.libelle} ({i.unite}) — {periode}, "
                      f"niveau {i.granularite_geo_min}")
    if not lignes:
        return None, []
    return (
        f"{len(lignes)} indicateurs sont disponibles :\n\n" +
        "\n".join(lignes) +
        "\n\nToute question portant sur un autre domaine — prix, éducation, "
        "santé, agriculture, comptes nationaux — reçoit un refus explicite "
        "plutôt qu'une approximation.",
        [],
    )


TRAITEMENTS = {
    "difference_series": _difference_series,
    "recensement": _recensement,
    "producteur": _producteur,
    "sources": _sources,
    "definition": _definition,
    "inventaire": _inventaire,
}


def reconnaitre(question):
    """
    Réponse documentaire si la question en est une, sinon None.

    Retourne {"message": str, "codes": [codes à proposer], "nature": str}.

    Ne lève jamais : une question documentaire mal servie doit retomber
    sur la chaîne ordinaire, pas faire échouer la requête.
    """
    nature = _nature(question)
    if nature is None:
        return None
    try:
        message, codes = TRAITEMENTS[nature]()
    except Exception:
        return None
    if not message:
        return None
    return {"message": message, "codes": codes, "nature": nature}