"""
StatSense AI — API

Quatre points d'entrée, dont un seul en écriture. La plateforme est en
lecture seule : les données entrent par le script de chargement, le
catalogue s'ajuste par l'interface d'administration.

    POST /api/ask/        question -> réponse complète
    GET  /api/catalogue/  indicateurs et zones, pour l'autocomplétion
    GET  /api/geo/        GeoJSON des régions
    GET  /api/historique/ questions récentes et suggestions

Traitement synchrone, sans file d'attente. Le cache absorbe la latence
du modèle sur les questions déjà posées.
"""

import json
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ai.chaine import repondre
from ai.client import client
from catalog.models import Indicateur
from geography.models import Niveau, Zone
from observations.models import Observation

from . import cache


@api_view(["POST"])
def ask(request):
    question = (request.data or {}).get("question", "")
    if not isinstance(question, str) or len(question.strip()) < 3:
        return Response({"statut": "refus", "motif": "question_vide",
                         "message": "Posez une question d'au moins "
                                    "trois caractères."}, status=400)

    if (request.data or {}).get("sans_cache") is not True:
        en_cache = cache.lire(question)
        if en_cache is not None:
            return Response(en_cache)

    reponse = repondre(question)
    cache.ecrire(question, reponse)
    return Response(reponse)


@api_view(["GET"])
def catalogue(request):
    """
    Inventaire public des données chargées.

    Ce n'est pas un simple point d'appui pour l'autocomplétion : c'est ce
    qui rend l'engagement de traçabilité vérifiable. N'importe qui peut
    consulter la totalité de ce que la plateforme exploite, et d'où ça
    vient.
    """
    out = []
    for i in Indicateur.objects.select_related("source").order_by("libelle"):
        periodes = sorted(
            Observation.objects.filter(indicateur=i)
            .values_list("periode", flat=True).distinct()
        )
        out.append({
            "code": i.code,
            "libelle": i.libelle,
            "unite": i.unite,
            "dimensions": i.dimensions,
            "granularite_min": i.granularite_geo_min,
            "frequence": i.frequence,
            "agregeable": i.agregeable,
            "derive": bool(i.derive_de),
            "observations": Observation.objects.filter(indicateur=i).count(),
            "periodes": {"debut": periodes[0], "fin": periodes[-1],
                         "points": len(periodes)} if periodes else None,
            "source": {"nom": i.source.nom, "url": i.source.url,
                       "plateforme": i.source.plateforme,
                       "date_extraction": str(i.source.date_extraction)},
        })

    zones = {
        niveau: Zone.objects.filter(niveau=niveau).count()
        for niveau, _ in Niveau.choices
    }

    return Response({
        "indicateurs": out,
        "zones": {k: v for k, v in zones.items() if v},
        "regions": list(
            Zone.objects.filter(niveau=Niveau.REGION)
            .order_by("nom").values("nom", "code", "geojson_id")
        ),
        "total_observations": Observation.objects.count(),
    })


@api_view(["GET"])
def geo(request):
    """Contours régionaux, servis tels quels. Aucune géométrie en base."""
    chemin = Path(settings.RAW_DIR) / "geo" / "sn.json"
    if not chemin.exists():
        raise Http404("Fichier de contours introuvable.")
    return FileResponse(open(chemin, "rb"), content_type="application/json")


@api_view(["GET"])
def historique(request):
    return Response({
        "recentes": cache.historique(10),
        "suggestions": cache.suggestions(8),
    })


@api_view(["GET"])
def sante(request):
    """État du service, utile avant une démonstration."""
    c = client()
    return Response({
        "modele": c.modele,
        "modele_disponible": c.disponible(),
        "observations": Observation.objects.count(),
        "indicateurs": Indicateur.objects.count(),
        "zones": Zone.objects.count(),
    })