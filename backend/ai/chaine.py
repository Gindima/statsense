"""
backend/ai/chaine.py

StatSense AI — Chaîne complète

C'est ici que les étapes s'enchaînent, et c'est toute la logique métier
de la plateforme :

    0. question documentaire ?      (code, avant tout appel au modèle)
    1. présélection du catalogue    (PostgreSQL, métadonnées)
    2. extraction du plan           (modèle, aucun chiffre en entrée)
    3. corrections déterministes    (zones, ventilations, périodes,
                                     cadrage, granularité)
    4. calcul                       (SQL paramétré, déterministe)
    5. narration                    (sur le résultat calculé)
    6. vérification des nombres     (code)
    7. restitution

Un seul nouvel essai en cas de plan rejeté, avec le message d'erreur
réinjecté. Au-delà, on demande une clarification plutôt que de boucler
indéfiniment.


TOUTE QUESTION N'EST PAS UNE DEMANDE DE CHIFFRE

L'étape 0 est la plus récente, et elle corrige la défaillance la plus
grave qu'on ait mesurée :

    « Quand a eu lieu le dernier recensement ? »
        -> valeur_simple · pop_totale · SENEGAL
        -> SENEGAL 18 126 342 personnes

Le modèle est sommé de choisir un indicateur ; il en choisit un. La
chaîne calcule correctement, et rend un effectif à qui demandait une
date — une réponse fausse, complète et confiante, sans aucun signe que la
question n'a pas été comprise. Tous les contrôles en aval sont muets :
l'indicateur existe, la zone existe, la valeur est juste.

La reconnaissance se fait donc en amont, sur une liste fermée de
formulations, et la réponse est construite depuis le catalogue et les
observations. Voir documentaire.py.


CE QUE LE MODÈLE PRODUIT, ET CE QU'IL NE PRODUIT PLUS

Six éléments du plan lui ont été retirés, un par un, chaque fois après
avoir mesuré qu'il s'en acquittait mal :

    zones        les noms des exemples du prompt se recopiaient dans la
                 réponse                                     -> zones.py
    ventilations le filtre était omis, et une demande
                 impossible passait pour ordinaire          -> filtres.py
    périodes     l'année était omise une fois sur trois, et
                 le moteur répondait pour 2023              -> periodes.py
    ordre        « les plus grands » produisait un tri
                 croissant : le classement exactement
                 inversé                                    -> cadrage.py
    top_n        en l'absence de nombre dans la question,
                 le modèle produisait 1, et le classement
                 ne rendait qu'une ligne                    -> cadrage.py
    niveau       un niveau plus fin que le niveau publié
                 faisait refuser une question qui avait
                 une réponse                            -> granularite.py

Le motif est le même six fois : chacun de ces éléments a une forme
FERMÉE — soixante-et-une zones, quatre modalités, quatre chiffres,
deux sens de tri, un nombre, cinq niveaux. Une forme fermée se reconnaît
par le code, sans faillir.

Il reste au modèle ce qu'il est seul à pouvoir faire : reconnaître
l'intention et nommer l'indicateur. Et s'il se trompe sur l'indicateur,
le catalogue fermé le rattrape.

Conséquence directe sur le risque d'hallucination : sur six des huit
champs du plan, une erreur du modèle n'a plus d'effet, parce qu'il ne les
remplit plus.


UN REFUS DU MOTEUR PRIME SUR UN DOUTE DU MODÈLE

La version antérieure testait `plan["clarification"]` AVANT d'exécuter le
moteur. Une clarification produite par le modèle court-circuitait donc
tous les contrôles portant sur les données : « la population de Dakar en
2010 » n'atteignait jamais le contrôle de période. Mesuré : les refus sont
tombés de 100 % à 0 % le jour où un exemple du prompt a appris au modèle
à produire des clarifications.

L'ordre est maintenant l'inverse, et c'est un principe : le moteur refuse
avec un motif et une source, le modèle n'exprime qu'une incertitude. On
ne s'arrête avant le calcul que si le plan est réellement inexploitable —
c'est-à-dire sans indicateur.
"""

import logging
import time
import re

from analytics.moteur import executer
from analytics.resultats import ErreurAnalyse

from .client import (
    ModeleInjoignable,
    ReponseIllisible,
    client,
    extraire_json,
)
from .documentaire import reconnaitre
from .filtres import corriger_filtres
from .granularite import corriger_granularite
from .narration import raconter
from .periodes import corriger_periode
from .ages import _norm as _norm_age, age_cite, age_servi, tranches_citees
from .plan import PlanInvalide, corriger_indicateur, repli, valider
from .prompts import (
    SYSTEME_EXTRACTION,
    prompt_correction,
    prompt_extraction,
)
from .recherche import fiches, rechercher, zones_connues
from .cadrage import (corriger_cadrage, corriger_comparaison, deux_sexes,
                      maille_demandee, seuil_cite, classement_evolution, statistique_zones,
                      croisement_cite, projection_demandee, etapes_multiples, comptes_croises,
                      part_menages, repartition_de_zones, double_superlatif)
from .zones import corriger_zones, niveau_de_zone


logger = logging.getLogger(__name__)

SEUIL_CONFIANCE = 0.4

# Température nulle : le même prompt doit donner le même plan. À 0.1, un
# test passait deux fois sur trois et l'on ne pouvait pas distinguer une
# régression d'un tirage.
TEMPERATURE = 0.0

# Seconde tentative après une réponse illisible : il faut un tirage
# DIFFÉRENT. À température 0, rejouer le même prompt reproduirait la même
# sortie fautive — une nouvelle tentative qui ne peut pas différer n'en
# est pas une. La reproductibilité des tests est préservée : seul le
# premier essai est déterministe, et c'est lui que les tests observent.
TEMPERATURE_RETENTATIVE = 0.2


def _extraire(question, candidats):
    """
    Traduit la question en plan.

    Trois échecs possibles, et ils ne se valent pas.

    Un modèle INJOIGNABLE est une panne : le repli déterministe garde la
    plateforme utilisable, et réessayer ne servirait à rien.

    Une réponse ILLISIBLE — JSON tronqué, mal échappé, absent — est une
    génération ratée alors que le modèle répondait. On rejoue le MÊME
    prompt, à température non nulle pour obtenir un autre tirage. Lui
    donner `prompt_correction` serait une erreur : ce prompt est fait
    pour corriger un plan mal rempli, il montre au modèle un plan vide et
    un message du genre « Unterminated string » — aucune information
    exploitable — et il ne reporte pas les fiches d'indicateurs, si bien
    que le modèle n'a plus de catalogue sous les yeux et ne peut nommer
    personne. Mesuré : la seconde tentative rendait alors
    `indicateur: null`.

    Un plan INVALIDE est une réponse lisible mais hors contrat. Là, le
    contenu EST la cause, et `prompt_correction` est le bon outil : il
    réinjecte le plan fautif et l'erreur.

    Après deux réponses inexploitables, on demande une précision. Deviner
    l'intention serait pire que les trois.
    """
    c = client()
    fiches_ind = fiches(candidats)
    zones = zones_connues()

    prompt = prompt_extraction(question, fiches_ind, zones)
    brut = None

    for tentative in (1, 2):
        try:
            reponse = c.completer(
                prompt, systeme=SYSTEME_EXTRACTION, json_attendu=True,
                max_tokens=300,
                temperature=TEMPERATURE if tentative == 1
                else TEMPERATURE_RETENTATIVE,
            )
            brut = extraire_json(reponse)
            return valider(brut), {
                "origine": "modele",
                "tentatives": tentative,
                "latence_s": round(c.derniere_latence or 0, 2),
            }

        except ModeleInjoignable as e:
            # Panne du service : le repli garde la plateforme utilisable.
            logger.warning("Modèle injoignable (%s), repli déterministe", e)
            return repli(question, candidats), {
                "origine": "repli", "raison": str(e),
            }

        except ReponseIllisible as e:
            if tentative == 1:
                # Même prompt — il porte les fiches d'indicateurs, et les
                # perdre coûterait l'indicateur. Seule la température
                # change, pour obtenir un autre tirage.
                logger.info("Réponse illisible (%s), nouveau tirage", e)
                continue
            return _plan_inexploitable(e)

        except PlanInvalide as e:
            if tentative == 1:
                # Ici le contenu est la cause : on le réinjecte.
                logger.info("Plan hors contrat (%s), correction", e)
                prompt = prompt_correction(question, brut or {}, str(e))
                continue
            return _plan_inexploitable(e)

    return repli(question, candidats), {"origine": "repli"}


def _plan_inexploitable(e):
    """
    Deux réponses inexploitables : on demande une précision plutôt que de
    retenir un indicateur approchant.
    """
    logger.warning("Plan inexploitable après deux essais : %s", e)
    return {
        "methode": "valeur_simple", "indicateur": None,
        "zones": [], "niveau": None,
        "periode": {"debut": None, "fin": None},
        "filtres": {}, "dimension": None, "top_n": None,
        "ordre": "desc", "confiance": 0.0,
        "clarification": "Je n'ai pas réussi à interpréter cette "
                         "demande. Reformulez-la, ou choisissez "
                         "un indicateur ci-dessous.",
    }, {"origine": "echec", "raison": str(e)}


def _refus(message, motif, alternatives=None, plan=None, meta=None):
    return {
        "statut": "refus",
        "message": message,
        "motif": motif,
        "alternatives": alternatives or [],
        "plan": plan,
        "meta": meta or {},
    }


def _clarification(message, candidats, plan, meta):
    return {
        "statut": "clarification",
        "message": message,
        "suggestions": [
            {"code": i.code, "libelle": i.libelle} for i in candidats[:4]
        ],
        "plan": plan,
        "meta": meta,
    }


def _documentaire(doc, debut):
    """
    Réponse portant sur les données elles-mêmes.

    Rendue sous la forme d'une clarification : le frontend sait déjà
    l'afficher, avec son message et ses suggestions d'indicateurs. Elle
    n'a pas de `plan` ni de `resultat`, parce qu'aucun calcul n'a eu lieu
    — et c'est justement ce qu'on voulait obtenir.
    """
    from catalog.models import Indicateur

    par_code = {
        i.code: i for i in
        Indicateur.objects.filter(code__in=doc["codes"] or [])
    }
    return {
        "statut": "clarification",
        "message": doc["message"],
        "suggestions": [
            {"code": c, "libelle": par_code[c].libelle}
            for c in (doc["codes"] or []) if c in par_code
        ],
        "plan": None,
        "meta": {
            "origine": "documentaire",
            "nature": doc["nature"],
            "duree_s": round(time.perf_counter() - debut, 2),
        },
    }


def repondre(question):
    """
    Point d'entrée unique de la plateforme.

    Retourne toujours un dictionnaire, jamais d'exception : un refus
    explicite est une réponse valide, et souvent la bonne.
    """
    debut = time.perf_counter()
    question = (question or "").strip()

    if len(question) < 3:
        return _refus("Question trop courte.", "question_vide")

    # 0. Question portant sur les données et non sur une valeur. Testée
    #    avant tout appel au modèle : lui demander un indicateur pour une
    #    question de date revient à lui demander de se tromper.
    doc = reconnaitre(question)
    if doc:
        return _documentaire(doc, debut)

    # 0 bis. Analyses non proposées : refus immédiat, sans appel au modèle.

    if statistique_zones(question):
        return _refus(
            "La médiane et les autres statistiques de dispersion entre zones "
            "ne sont pas encore calculées. Un classement range les zones et "
            "permet de situer chacune.", "analyse_non_traitee")

    seuil = seuil_cite(question)
    if seuil:
        return _refus(
            f"La sélection des zones au-dessus ou en dessous d'une valeur "
            f"({seuil}) n'est pas proposée. Un classement range les zones "
            f"dans l'ordre et permet de lire celles qui dépassent ce seuil.",
            "analyse_non_traitee")

    croises = croisement_cite(question)
    if croises:
        noms = " et ".join(croises) if len(croises) > 1 else croises[0]
        return _refus(
            f"Croiser plusieurs indicateurs ({noms}) n'est pas encore "
            f"proposé : chaque réponse porte sur un seul indicateur, pour "
            f"que chaque chiffre reste rattaché à sa source. Posez une "
            f"question par indicateur.",
            "analyse_non_traitee")

    if projection_demandee(question):
        return _refus(
            "Prolonger une tendance n'est pas proposé : la plateforme "
            "restitue les valeurs publiées, sans extrapoler. Les seules "
            "projections disponibles sont celles de la population, publiées "
            "par l'ANSD.", "analyse_non_traitee")

    if classement_evolution(question):
        return _refus(
            "Comparer ou classer plusieurs zones selon leur évolution "
            "(progression, hausse, baisse) n'est pas encore proposé. La "
            "plateforme compare des zones à une date, ou suit l'évolution "
            "d'une zone dans le temps.",
            "analyse_non_traitee")

    if etapes_multiples(question):
        return _refus(
            "Cette question enchaîne deux calculs : choisir des zones selon "
            "un premier critère, puis calculer un autre indicateur sur ces "
            "zones. Posez-les l'une après l'autre.",
            "analyse_non_traitee",
            alternatives=["Quels sont les cinq quartiers les plus peuplés "
                          "de Dakar ?",
                          "Quelle est la taille moyenne des ménages à Dakar ?"])

    comptes = comptes_croises(question)
    if comptes:
        return _refus(
            f"Combiner deux effectifs ({' et '.join(comptes)}) n'est pas "
            f"proposé : chaque réponse porte sur un seul indicateur. Le "
            f"rapport « ménages par concession », lui, est publié.",
            "analyse_non_traitee",
            alternatives=["Combien de ménages compte Dakar ?",
                          "Combien de ménages par concession à Dakar ?"])

    if part_menages(question):
        return _refus(
            "La part des ménages d'une zone dans le total national n'est pas "
            "calculée ; seule la part de la population (poids démographique) "
            "l'est.",
            "analyse_non_traitee",
            alternatives=["Quelle part de la population vit dans la région "
                          "de Dakar ?",
                          "Combien de ménages compte la région de Dakar ?"])

    if repartition_de_zones(question):
        return _refus(
            "Répartir les zones elles-mêmes en classes (par exemple les "
            "quartiers selon leur taille de ménage) n'est pas encore proposé. "
            "Un classement range les zones selon l'indicateur.",
            "analyse_non_traitee",
            alternatives=["Quels quartiers ont la taille moyenne des ménages "
                          "la plus élevée ?"])

    if double_superlatif(question):
        return _refus(
            "Vérifier si les zones en tête pour un indicateur le sont aussi "
            "pour un autre demande de croiser deux classements, ce qui n'est "
            "pas encore proposé. Posez une question par indicateur.",
            "analyse_non_traitee")

    # 1. Présélection du catalogue : le modèle choisira dans cette liste.
    candidats = rechercher(question)
    if not candidats:
        return _refus(
            "Aucun indicateur du catalogue ne correspond à cette question.",
            "aucun_candidat",
            alternatives=["consulter la page catalogue des données "
                          "disponibles"],
        )

    # 2. Extraction puis validation de forme.
    plan, meta_plan = _extraire(question, candidats)

    # 3. Corrections déterministes. L'ordre compte deux fois : le cadrage
    #    dépend de `dimension`, que corriger_filtres peut avoir vidée, et
    #    la granularité dépend de `niveau`, que le cadrage peut avoir
    #    écrit en requalifiant une répartition en classement.
    plan = corriger_zones(plan, question)
    plan["niveau_zone"] = (niveau_de_zone(question, plan["zones"][0])
                           if plan.get("zones") else None) \
        or plan.get("niveau_zone")
    plan = corriger_indicateur(plan, question)
    plan = corriger_filtres(plan, question)
    plan = corriger_periode(plan, question)
    plan = corriger_cadrage(plan, question)
    plan = corriger_comparaison(plan, question)
    plan = corriger_granularite(plan)

    # Un plan sans indicateur est le seul cas où l'on s'arrête avant le
    # calcul : il n'y a rien à vérifier. Une clarification accompagnant un
    # plan exploitable ne bloque pas — le moteur sait refuser avec un
    # motif, ce que le modèle ne sait pas faire.
    if plan.get("indicateur") is None:
        return _clarification(
            plan.get("clarification")
            or "Quel indicateur souhaitez-vous consulter ?",
            candidats, plan, meta_plan,
        )

    if plan.get("clarification"):
        # Conservée pour information, sans effet sur le déroulement.
        meta_plan = {**meta_plan, "doute_modele": plan["clarification"]}

    # Tranche d'âge ajoutée par le modèle seul. Constaté : « Combien
    # d'hommes vivent dans la région de Matam ? » -> pop_region, age=E15T64,
    # refusé faute de données par âge à la région.
    if (plan.get("indicateur") == "pop_region"
            and plan.get("methode") != "repartition"
            and not age_cite(question)
            and not re.search(r"\bage|\bans\b|travail|activ|jeune|enfant|agee|vieux",
                              _norm_age(question))):
        plan["filtres"] = {k: v for k, v in (plan.get("filtres") or {}).items()
                           if k != "age"}
        if plan.get("dimension") == "age":
            plan["dimension"] = None

    # (B) Sans année ni âge, le recensement fait foi. Constaté : la même
    # question rendait 2023 ou 2025 selon l'indicateur choisi par le modèle.
    if (plan.get("indicateur") == "pop_region"
            and plan.get("methode") in ("valeur_simple", "classement",
                                        "comparaison", "geographique")
            and not any((plan.get("periode") or {}).values())
            and "age" not in (plan.get("filtres") or {})
            and plan.get("dimension") != "age"
            and not age_cite(question)):
        plan["indicateur"] = "pop_totale"
        if (plan.get("filtres") or {}).get("sexe") == "M":
            plan["filtres"]["sexe"] = "H"

    # (C) Groupe d'âge. Somme exacte des tranches publiées quand les bornes
    # le permettent ; refus explicite sinon.
    groupe = age_cite(question)
    tranches, precision = tranches_citees(question) if groupe else (None, None)
    repartition_age = (plan.get("methode") == "repartition"
                       and plan.get("dimension") == "age")

    # Le modèle choisit parfois un autre indicateur ventilé par âge (le
    # chômage) pour une question qui ne parle que de population. Constaté :
    # « plus d'hommes que de femmes chez les 20 ans et plus » -> chômage,
    # tranche inventée Y20T100.
    MOTS_AUTRES = ("chomage", "emploi", "activite", "natalite", "naissance",
                   "mortalite", "deces", "electricite", "eclairage", "eau",
                   "bien etre", "menage", "menages", "concession")
    texte_q = f" {_norm_age(question)} "
    if (tranches and plan.get("indicateur") not in (
            "pop_totale", "pop_region", "rapport_masculinite",
            "part_population")
            and not any(f" {m} " in texte_q for m in MOTS_AUTRES)):
        plan["indicateur"] = ("rapport_masculinite" if deux_sexes(question)
                              else "pop_region")
        plan["filtres"] = {k: v for k, v in (plan.get("filtres") or {}).items()
                           if k == "sexe"}

    # Part d'un groupe d'âge : pas encore calculée. On le dit.
    if tranches and plan.get("indicateur") == "part_population":
        return _refus(
            f"La part de « {groupe} » dans la population n'est pas encore "
            f"calculée ; l'effectif l'est.", "age_non_traite",
            alternatives=[f"Combien de personnes de {groupe} vivent au "
                          f"Sénégal ?"],
            plan=plan, meta=meta_plan,
        )

    if (tranches and not repartition_age
            and plan.get("indicateur") in ("pop_totale", "pop_region",
                                           "rapport_masculinite")):
        nommees = [z for z in plan.get("zones") or [] if z != "SENEGAL"]
        if nommees or plan.get("methode") not in ("valeur_simple",
                                                  "comparaison", "evolution"):
            return _refus(
                f"Les effectifs par âge (« {groupe} ») ne sont publiés qu'au "
                f"niveau national, dans les projections de population "
                f"2016-2025.", "age_non_traite",
                alternatives=[f"Combien de personnes de {groupe} vivent au "
                              f"Sénégal ?"],
                plan=plan, meta=meta_plan,
            )
        if plan["indicateur"] == "rapport_masculinite":
            plan["methode"], plan["dimension"] = "comparaison", "sexe"
        plan["indicateur"] = "pop_region"
        filtres = {k: v for k, v in (plan.get("filtres") or {}).items()
                   if k != "age"}
        if filtres.get("sexe") == "H":
            filtres["sexe"] = "M"
        plan["filtres"] = {**filtres, "age": tranches}
        if (plan["methode"] != "evolution"
                and not any((plan.get("periode") or {}).values())):
            plan["periode"] = {"debut": "2023", "fin": "2023"}

    elif groupe and not age_servi(plan):
        return _refus(
            f"« {groupe} » ne correspond pas exactement aux tranches de 5 ans "
            f"publiées par l'ANSD. Précisez une tranche, par exemple « moins "
            f"de 15 ans », « de 15 à 34 ans » ou « 60 ans et plus ».",
            "age_non_traite",
            alternatives=["Combien de personnes âgées de 15 à 34 ans vivent "
                          "au Sénégal ?",
                          "Quelle est la répartition de la population par "
                          "tranche d'âge ?"],
            plan=plan, meta=meta_plan,
        )

    # Maille demandée plus fine que la publication. Constaté : « le
    # chômage de chaque quartier de Dakar » rendait les 14 régions.
    maille = maille_demandee(question)
    if maille:
        from analytics.donnees import get_indicateur, verifier_granularite
        try:
            verifier_granularite(get_indicateur(plan["indicateur"]), maille)
        except ErreurAnalyse as e:
            return _refus(e.message, e.motif, e.alternatives, plan, meta_plan)

    # Le RGPH-5 n'a qu'un millésime. Une autre année demandée « selon le
    # recensement » ne doit pas être servie en silence par les projections.
    texte_rgph = _norm_age(question)
    p = plan.get("periode") or {}
    annees = {str(v) for v in (p.get("debut"), p.get("fin")) if v}
    if ("rgph" in texte_rgph or "recens" in texte_rgph) \
            and annees and annees != {"2023"}:
        autres = ", ".join(sorted(annees - {"2023"}))
        return _refus(
            f"Le RGPH-5 porte sur l'année 2023 : il n'existe pas de population "
            f"recensée pour {autres}. Pour une autre année, les projections de "
            f"population couvrent 2016-2025, jusqu'au niveau du département.",
            "periode_non_couverte",
            alternatives=["Quelle est la population recensée au Sénégal en 2023 ?"],
            plan=plan, meta=meta_plan,
        )

    # 4. Calcul. La validation portant sur les données a lieu ici.
    try:
        resultat = executer(plan)
    except ErreurAnalyse as e:
        return _refus(e.message, e.motif, e.alternatives, plan, meta_plan)

    # Tranche ou somme de tranches retenue : toujours dite.
    age = (plan.get("filtres") or {}).get("age")
    if groupe and age:
        from analytics.repartition import _libelle_age
        if isinstance(age, list):
            note = (f"« {groupe} » : somme des {len(age)} tranches de 5 ans "
                    f"publiées ({_libelle_age(age[0])} … "
                    f"{_libelle_age(age[-1])}), projections nationales.")
            if precision:
                note += " " + precision
        else:
            note = (f"La question cite « {groupe} » ; tranche d'âge "
                    f"retenue : {_libelle_age(age)}.")
        resultat.notes.insert(0, note)

    # Rapport de féminité : la plateforme publie l'inverse.
    if (plan.get("indicateur") == "rapport_masculinite"
            and "feminite" in _norm_age(question)
            and len(resultat.lignes) == 1 and resultat.lignes[0]["valeur"]):
        inverse = 10000 / float(resultat.lignes[0]["valeur"])
        resultat.notes.insert(0, (
            f"Le rapport de féminité est l'inverse du rapport de "
            f"masculinité publié : {inverse:.2f} femmes pour 100 hommes."
        ).replace(".", ",", 1))

    if plan.get("inverse"):
        if plan["indicateur"] == "menages_par_concession":
            note = ("La base publie le nombre de ménages par concession ; "
                    "le nombre de concessions par ménage en est l'inverse.")
            if len(resultat.lignes) == 1 and resultat.lignes[0]["valeur"]:
                inv = 1 / float(resultat.lignes[0]["valeur"])
                note += (f" Ici : {inv:.2f} concession par ménage."
                         ).replace(".", ",", 1)
            elif plan.get("methode") == "classement":
                note += " Classement inversé en conséquence."
        else:
            note = ("Plus de ménages par habitant signifie des ménages plus "
                    "petits : le classement suit la taille moyenne des "
                    "ménages, dans l'ordre inverse.")
        resultat.notes.insert(0, note)

    # 5-6. Narration, puis vérification des nombres cités.
    texte, meta_texte = raconter(question, resultat)

    if plan.get("inverser_affichage"):
        resultat.lignes.reverse()
        resultat.notes.insert(0, "Sélection faite selon la question ; "
                                 "affichage dans l'ordre demandé.")
    return {
        "statut": "ok",
        "question": question,
        "plan": plan,
        "resultat": resultat.to_dict(),
        "texte": texte,
        "meta": {
            **meta_plan,
            "narration": meta_texte,
            "duree_s": round(time.perf_counter() - debut, 2),
            "candidats": [i.code for i in candidats],
        },
    }