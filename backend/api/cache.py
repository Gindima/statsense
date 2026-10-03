"""
StatSense AI — Cache des réponses

Une même question doit toujours produire la même réponse, et vite. C'est
vrai pour l'utilisateur, et c'est critique en démonstration : une
question préparée répond instantanément au lieu d'attendre le modèle.

Seules les réponses abouties sont mises en cache. Un refus ou une
demande de clarification dépend de l'état du catalogue et des données,
qui peut changer entre deux chargements.
"""

import hashlib
import re
import unicodedata

from .models import Requete


def normaliser(question):
    """
    Deux formulations équivalentes doivent tomber sur la même entrée.
    « Combien d'habitants à Thiès ? » et « combien d habitants a thies »
    donnent la même empreinte.
    """
    s = unicodedata.normalize("NFD", (question or "").strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"['’`]", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def empreinte(question):
    return hashlib.sha256(normaliser(question).encode()).hexdigest()


def lire(question):
    """Réponse en cache, ou None. Incrémente le compteur d'usage."""
    r = (Requete.objects
         .filter(empreinte=empreinte(question), statut="ok")
         .order_by("-epingle", "-cree_le")
         .first())
    if r is None:
        return None

    Requete.objects.filter(pk=r.pk).update(utilisee=r.utilisee + 1)

    reponse = dict(r.reponse)
    meta = dict(reponse.get("meta") or {})
    meta["cache"] = True
    meta["duree_s"] = 0.0
    reponse["meta"] = meta
    return reponse


def ecrire(question, reponse, epingle=False):
    """N'enregistre que les réponses abouties."""
    if reponse.get("statut") != "ok":
        return None

    meta = reponse.get("meta") or {}
    plan = reponse.get("plan") or {}

    return Requete.objects.create(
        empreinte=empreinte(question),
        question=question.strip(),
        statut=reponse["statut"],
        reponse=reponse,
        duree_s=meta.get("duree_s"),
        origine_plan=meta.get("origine", ""),
        indicateur=plan.get("indicateur") or "",
        methode=plan.get("methode") or "",
        epingle=epingle,
    )


def historique(n=10):
    vus, out = set(), []
    for r in Requete.objects.filter(statut="ok")[:n * 4]:
        if r.empreinte in vus:
            continue
        vus.add(r.empreinte)
        out.append({
            "question": r.question,
            "methode": r.methode,
            "indicateur": r.indicateur,
            "cree_le": r.cree_le.isoformat(),
        })
        if len(out) >= n:
            break
    return out


def suggestions(n=8):
    """
    Questions proposées sur la page d'accueil.

    Les questions épinglées d'abord — ce sont celles de la démonstration,
    préchauffées donc instantanées. Complétées par les plus utilisées.
    """
    epinglees = list(
        Requete.objects.filter(epingle=True, statut="ok")
        .values_list("question", flat=True)
    )
    if len(epinglees) >= n:
        return epinglees[:n]

    frequentes = (
        Requete.objects.filter(statut="ok", epingle=False)
        .order_by("-utilisee")[:n * 2]
    )
    vus = {normaliser(q) for q in epinglees}
    for r in frequentes:
        if normaliser(r.question) not in vus:
            epinglees.append(r.question)
            vus.add(normaliser(r.question))
        if len(epinglees) >= n:
            break
    return epinglees