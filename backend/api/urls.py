from django.urls import path

from . import views

urlpatterns = [
    path("ask/", views.ask, name="ask"),
    path("catalogue/", views.catalogue, name="catalogue"),
    path("geo/", views.geo, name="geo"),
    path("historique/", views.historique, name="historique"),
    path("sante/", views.sante, name="sante"),
]