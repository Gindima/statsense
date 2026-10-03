"""
backend/ai/periodes.py

StatSense AI — Reconnaissance des périodes citées dans une question

Dernier des trois éléments retirés au modèle, après les zones et les
ventilations, et pour la même raison : une année est une forme fermée —
quatre chiffres — que le code reconnaît sans faillir, là où le modèle
l'omet une fois sur trois.

L'enjeu est le même que pour les filtres : permettre au moteur de
REFUSER. « La population de Dakar en 2010 » doit produire un refus,
puisque le recensement chargé ne couvre que 2023. Si l'année n'est pas
dans le plan, le moteur prend la dernière période disponible et répond
2023 sans que rien ne signale le glissement — une réponse exacte à une
autre question que celle posée.

Sont reconnus : une année seule, un intervalle, un trimestre, et les
formulations d'ouverture (« depuis 2008 ») ou de clôture (« jusqu'en
2020 »).
"""

import re
import unicodedata

# Bornes de vraisemblance. Au-delà, un nombre à quatre chiffres dans une
# question statistique est plus probablement une valeur qu'une année.
MIN_ANNEE, MAX_ANNEE = 1900, 2030

DEPUIS = ("depuis", "a partir de", "des ", "entre")
JUSQUA = ("jusqu a", "jusqu en", "jusque", "avant")


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def periodes_citees(question):
    """
    Retourne (debut, fin) tels que la question les exprime, ou (None,
    None). Les valeurs sont des entiers, ou des chaînes « 2026-Q1 » pour
    un trimestre.
    """
    brut = str(question or "")
    texte = _norm(brut)

    # Trimestres : « 2026-Q1 », « T1 2026 », « premier trimestre 2026 ».
    trimestres = re.findall(r"\b((?:19|20)\d{2})\s*[-\s]?[qt]([1-4])\b", texte)
    trimestres += [(a, t) for t, a in
                   re.findall(r"\b[qt]([1-4])\s*[-\s]?((?:19|20)\d{2})\b",
                              texte)]
    if trimestres:
        valeurs = sorted(f"{a}-Q{t}" for a, t in trimestres)
        return (valeurs[0], valeurs[-1]) if len(valeurs) > 1 \
            else (None, valeurs[0])

    annees = sorted({
        int(a) for a in re.findall(r"\b(?:19|20)\d{2}\b", texte)
        if MIN_ANNEE <= int(a) <= MAX_ANNEE
    })

    if not annees:
        return None, None

    if len(annees) >= 2:
        return annees[0], annees[-1]

    seule = annees[0]
    if any(m in texte for m in DEPUIS):
        return seule, None
    if any(m in texte for m in JUSQUA):
        return None, seule
    return None, seule


def corriger_periode(plan, question):
    """
    Impose au plan les périodes citées dans la question.

    Ce que la question nomme fait autorité. En l'absence d'année citée,
    ce que le modèle a proposé est conservé : il peut avoir interprété
    « ces cinq dernières années » ou « au dernier trimestre », que cette
    fonction ne sait pas lire.
    """
    debut, fin = periodes_citees(question)
    if debut is None and fin is None:
        return plan

    p = dict(plan.get("periode") or {})
    if debut is not None:
        p["debut"] = debut
    if fin is not None:
        p["fin"] = fin
        # Une valeur ponctuelle porte sur l'année citée, pas sur un
        # intervalle ouvert qui se refermerait sur la dernière période
        # disponible.
        if plan.get("methode") == "valeur_simple" and debut is None:
            p["debut"] = fin

    plan["periode"] = p
    return plan