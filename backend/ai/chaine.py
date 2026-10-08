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

from analytics.moteur import executer
from analytics.resultats import ErreurAnalyse

from .cadrage import corriger_cadrage
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

from .plan import PlanInvalide, corriger_indicateur, repli, valider
from .prompts import (
    SYSTEME_EXTRACTION,
    prompt_correction,
    prompt_extraction,
)
from .recherche import fiches, rechercher, zones_connues
from .zones import corriger_zones

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
    plan = corriger_indicateur(plan, question)
    plan = corriger_filtres(plan, question)
    plan = corriger_periode(plan, question)
    plan = corriger_cadrage(plan, question)
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

    # 4. Calcul. La validation portant sur les données a lieu ici.
    try:
        resultat = executer(plan)
    except ErreurAnalyse as e:
        return _refus(e.message, e.motif, e.alternatives, plan, meta_plan)

    # 5-6. Narration, puis vérification des nombres cités.
    texte, meta_texte = raconter(question, resultat)

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