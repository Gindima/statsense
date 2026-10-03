from django.contrib import admin

from .models import Requete


@admin.register(Requete)
class RequeteAdmin(admin.ModelAdmin):
    """
    Sert surtout à épingler les questions de démonstration : une question
    épinglée reste en cache et apparaît dans les suggestions de la page
    d'accueil.
    """

    list_display = ("question", "statut", "methode", "indicateur",
                    "duree_s", "origine_plan", "utilisee", "epingle",
                    "cree_le")
    list_filter = ("statut", "methode", "origine_plan", "epingle")
    search_fields = ("question", "indicateur")
    list_editable = ("epingle",)
    readonly_fields = ("empreinte", "reponse", "cree_le")
    date_hierarchy = "cree_le"