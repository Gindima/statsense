"""
backend/config/urls.py

StatSense AI — Routage racine

L'ordre compte. `api/` et `admin/` d'abord, puis la route attrape-tout qui
renvoie le frontend.

POURQUOI UNE ROUTE ATTRAPE-TOUT

Le frontend est une application à page unique : ses adresses internes
— /catalogue, /resultat — n'existent pas côté serveur. Sans cette route,
ouvrir directement une de ces adresses, ou simplement recharger la page,
renvoie une 404. WhiteNoise sert déjà index.html pour « / » ; la route
ci-dessous couvre tout le reste.

L'expression exclut api/, admin/ et static/ : une faute de frappe dans une
URL d'API doit produire une erreur de l'API, pas la page d'accueil du
frontend — sans quoi le débogage devient un jeu de devinettes.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
]

if settings.FRONTEND_PRET:
    urlpatterns += [
        re_path(r"^(?!api/|admin/|static/).*$",
                TemplateView.as_view(template_name="index.html"),
                name="frontend"),
    ]