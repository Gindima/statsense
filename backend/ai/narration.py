"""
StatSense AI — Narration et garde-fou

Le modèle reçoit ici, pour la première fois, des chiffres : ceux que le
moteur vient de calculer. Il n'a toujours aucun accès à la base.

Le garde-fou est le troisième et dernier verrou du système. Il extrait
tous les nombres du texte produit et vérifie que chacun provient des
résultats. Un nombre étranger fait rejeter la narration, remplacée par un
résumé factuel produit par le code.

Ce n'est pas une intention mais une propriété vérifiable : le système ne
peut pas afficher un chiffre qu'il n'a pas calculé.
"""

import logging
import re
from decimal import Decimal

from .client import ErreurLLM, client
from .prompts import GABARIT_NARRATION, SYSTEME_NARRATION, prompt_narration
from django.conf import settings

logger = logging.getLogger(__name__)

# Tolérance d'arrondi : le modèle peut écrire « 4 millions » pour
# 4 003 205, ou arrondir un pourcentage à l'unité.
TOLERANCE = Decimal("0.05")      # 5 %

# Nombres toujours acceptés : rangs, années, petits entiers de discours.
BANALS = set(range(0, 101)) | set(range(1900, 2101))


def _nombres(texte):
    """Extrait les nombres d'un texte français (espaces, virgules)."""
    out = []
    for brut in re.findall(r"\d[\d\u202f\u00a0 ]*(?:[.,]\d+)?", texte):
        s = (brut.replace("\u202f", "").replace("\u00a0", "")
             .replace(" ", "").replace(",", "."))
        try:
            out.append(Decimal(s))
        except Exception:
            continue
    return out


def _autorises(resultat):
    """Valeurs que le modèle a le droit de citer."""
    ok = set()

    for ligne in resultat.lignes:
        for v in ligne.values():
            if isinstance(v, (int, float, Decimal)):
                ok.add(Decimal(str(v)))

    for cle in ("variation_pct", "variation_absolue", "tcam_pct",
                "min", "max", "couvertes", "points"):
        v = (resultat.meta or {}).get(cle)
        if isinstance(v, (int, float, Decimal)):
            ok.add(Decimal(str(v)))

    ok.add(Decimal(len(resultat.lignes)))

    # Somme et moyenne : le modèle peut légitimement les mentionner sur un
    # indicateur agrégeable.
    valeurs = [Decimal(str(l["valeur"])) for l in resultat.lignes
               if isinstance(l.get("valeur"), (int, float, Decimal))]
    if valeurs:
        total = sum(valeurs)
        ok.add(total)
        ok.add(total / len(valeurs))

    return ok


def _accepte(n, autorises):
    if n in BANALS and n == n.to_integral_value():
        return True
    for a in autorises:
        if a == 0:
            if n == 0:
                return True
            continue
        if abs(n - a) / abs(a) <= TOLERANCE:
            return True
        # Le modèle peut écrire « 4 millions » pour 4 003 205.
        for facteur in (Decimal(1000), Decimal(1000000)):
            if abs(n - a / facteur) / abs(a / facteur) <= TOLERANCE:
                return True
    return False


def verifier(texte, resultat):
    """
    Retourne (texte, chiffres_rejetes). Un texte contenant un nombre
    inconnu est rejeté en bloc : on ne corrige pas, on remplace.
    """
    autorises = _autorises(resultat)
    rejetes = [n for n in _nombres(texte) if not _accepte(n, autorises)]
    return (None if rejetes else texte), rejetes

SEXES = {"H": "hommes", "M": "hommes", "F": "femmes"}

def _precision(m):
    """« (hommes) » quand le résultat est filtré par sexe."""
    s = ((m or {}).get("filtres") or {}).get("sexe")
    return f" ({SEXES[s]})" if s in SEXES else ""

def resume_factuel(question, resultat):
    """
    Texte de repli, produit par le code. Aucun risque d'hallucination,
    puisqu'il n'est pas généré.
    """
    m = resultat.meta or {}
    ind = m.get("indicateur", "L'indicateur demandé") + _precision(m)
    n = len(resultat.lignes)

    if resultat.chart_hint == "kpi" and n == 1:
        l = resultat.lignes[0]
        phrase = (f"{ind} : {_fmt(l['valeur'])} {resultat.unite} "
                  f"pour {l.get('zone', '')} en {l.get('periode', m.get('periode', ''))}.")
    elif resultat.chart_hint == "line":
        d, f = resultat.lignes[0], resultat.lignes[-1]
        phrase = (f"{ind} pour {m.get('zone', '')} : {_fmt(d['valeur'])} "
                  f"{resultat.unite} en {d['periode']}, "
                  f"{_fmt(f['valeur'])} {resultat.unite} en {f['periode']} "
                  f"({n} valeurs publiées).")
    elif "ecart" in m:
        # Comparaison : chaque valeur nommée, sans « en tête », qui serait
        # faux quand les lignes suivent l'ordre des modalités.
        valeurs = " ; ".join(
            f"{l.get('zone', '')} : {_fmt(l['valeur'])} {resultat.unite}"
            for l in resultat.lignes)
        phrase = f"{ind} ({m.get('periode', '')}) — {valeurs}."
    else:
        tete = resultat.lignes[0]
        if m.get("unique"):
            # « Quelle région… » attend UNE réponse : on la nomme, puis on
            # donne les suivantes pour montrer si elle se détache.
            sens = ("la plus faible valeur" if m.get("ordre") == "asc"
                    else "la plus forte valeur")
            phrase = (f"{tete.get('zone', '')} a {sens} : "
                      f"{_fmt(tete['valeur'])} {resultat.unite} "
                      f"({m.get('periode', '')}).")
            suite = ", ".join(l.get("zone", "") for l in resultat.lignes[1:4])
            if suite:
                phrase += f" Suivent : {suite}."
        else:
            phrase = (f"{ind} : {n} zone(s) classée(s), "
                      f"{tete.get('zone', '')} en tête avec "
                      f"{_fmt(tete['valeur'])} {resultat.unite}.")

    if resultat.notes:
        phrase += " " + " ".join(resultat.notes)
    return phrase

def _fmt(v):
    v = float(v)
    if v == int(v) and abs(v) >= 1000:
        return f"{int(v):,}".replace(",", " ")
    s = f"{v:,.2f}".replace(",", " ").rstrip("0").rstrip(".")
    return s.replace(".", ",")

def raconter(question, resultat):
    """
    Point d'entrée. Retourne (texte, meta) — `meta` dit d'où vient le
    texte, information utile pour la démonstration comme pour le débogage.
    """
    if resultat.vide():
        return "Aucun résultat pour cette question.", {"origine": "code"}

    if not getattr(settings, "NARRATION_LLM", False):
        return resume_factuel(question, resultat), {"origine": "code"}

    c = client()
    try:
        brut = c.completer(
            prompt_narration(question, resultat),
            systeme=SYSTEME_NARRATION,
            max_tokens=250,
            temperature=0.2,
        )
    except ErreurLLM as e:
        logger.warning("Narration indisponible : %s", e)
        return resume_factuel(question, resultat), {
            "origine": "code", "raison": "modele_indisponible",
        }

    texte, rejetes = verifier(brut, resultat)
    if texte is None:
        logger.warning("Narration rejetée, chiffres absents des résultats : %s",
                       rejetes)
        return resume_factuel(question, resultat), {
            "origine": "code",
            "raison": "chiffres_non_verifies",
            "rejetes": [str(x) for x in rejetes],
        }

    return texte.strip(), {
        "origine": "modele",
        "latence_s": round(c.derniere_latence or 0, 2),
    }