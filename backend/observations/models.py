from django.contrib.postgres.indexes import GinIndex
from django.db import models

from catalog.models import Indicateur
from geography.models import Zone


class Observation(models.Model):
    """
    Format long : une ligne = une observation atomique.

    Pourquoi pas une table par jeu de données : chaque nouveau domaine
    imposerait de nouvelles migrations, de nouvelles requêtes et de
    nouvelles méthodes d'analyse. Ici, le PIB trimestriel national et la
    population au quartier passent par exactement le même moteur.

    C'est ce qui rend l'affirmation « l'architecture est extensible »
    vérifiable plutôt que déclarative.
    """

    indicateur = models.ForeignKey(Indicateur, on_delete=models.CASCADE,
                                   related_name="observations")
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE,
                             related_name="observations")

    # "2023" (ponctuel/annuel) ou "2026-Q1" (trimestriel).
    # Le tri lexicographique est chronologique dans les deux cas.
    periode = models.CharField(max_length=10, db_index=True)

    # Ventilations : {"sexe": "F"}. JSON parce que les dimensions varient
    # selon l'indicateur — des colonnes fixes seraient vides la plupart
    # du temps. Validé contre Indicateur.dimensions à l'ingestion.
    dims = models.JSONField(default=dict, blank=True)

    valeur = models.DecimalField(max_digits=20, decimal_places=4)

    # Rattachement au fichier d'origine : permet une purge ciblée lors
    # d'un rechargement en mode --append.
    chargement = models.ForeignKey(
        "catalog.Chargement", null=True, blank=True,
        on_delete=models.CASCADE, related_name="observations",
    )

    class Meta:
        verbose_name = "Observation"
        verbose_name_plural = "Observations"
        constraints = [
            # Une observation est identifiée par : quoi, où, quand,
            # ventilé comment. PostgreSQL normalise l'ordre des clés en
            # jsonb, donc {"sexe":"F"} est reconnu identique quel que
            # soit l'ordre d'écriture. Rend le doublon impossible même
            # si le script est relancé.
            models.UniqueConstraint(
                fields=["indicateur", "zone", "periode", "dims"],
                name="observation_unique",
            ),
        ]
        indexes = [
            # Index principal du moteur : couvre valeur_simple,
            # classement, evolution et geographique.
            models.Index(fields=["indicateur", "zone", "periode"],
                         name="obs_ind_zone_per"),
            # Classement et carte : filtre sur le niveau via la zone.
            models.Index(fields=["indicateur", "periode"],
                         name="obs_ind_per"),
            # Recherche sur les ventilations.
            GinIndex(fields=["dims"], name="obs_dims_gin"),
        ]

    def __str__(self):
        d = f" {self.dims}" if self.dims else ""
        return f"{self.indicateur.code}@{self.zone.nom}[{self.periode}]{d} = {self.valeur}"