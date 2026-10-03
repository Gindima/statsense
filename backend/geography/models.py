from django.db import models


class Niveau(models.TextChoices):
    REGION = "region", "Région"
    DEPARTEMENT = "departement", "Département"
    COMMUNE = "commune", "Commune"
    QUARTIER = "quartier", "Quartier / Village / Hameau"
    NATIONAL = "national", "National"


class Zone(models.Model):
    """
    Hiérarchie géographique auto-référente.

    Un seul modèle pour les cinq niveaux : le moteur d'analyse interroge
    `Zone.objects.filter(niveau=...)` sans savoir à l'avance de quel niveau
    il s'agit. Quatre tables séparées imposeraient de dupliquer chaque
    méthode d'analyse.

    `code` est construit par concaténation des noms normalisés :
        SN-DAKAR-DAKAR-GOREE-MBAMBARA
    Il est stable entre deux chargements, ce qui rend le seed idempotent.
    """

    code = models.CharField(max_length=255, unique=True, db_index=True)
    nom = models.CharField(max_length=150)
    niveau = models.CharField(max_length=20, choices=Niveau.choices)

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="enfants",
    )

    # Renseigné uniquement au niveau région : SNDK, SNTH...
    # Clé de jointure avec le GeoJSON servi au frontend.
    geojson_id = models.CharField(max_length=10, blank=True, db_index=True)
    sdmx_code = models.CharField(max_length=20, blank=True, default="",
                                 db_index=True)

    # COM_ARRT_VILLE du RGPH : commune d'arrondissement dans les grandes
    # villes. Attribut informatif, pas un niveau de la hiérarchie.
    com_arrt_ville = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = "Zone"
        verbose_name_plural = "Zones"
        ordering = ["niveau", "nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "nom"],
                name="zone_unique_dans_parent",
            ),
        ]
        indexes = [
            models.Index(fields=["niveau"]),
            models.Index(fields=["niveau", "parent"]),
        ]

    def __str__(self):
        return f"{self.nom} ({self.get_niveau_display()})"

    @property
    def chemin(self):
        """Fil d'Ariane : 'DAKAR > DAKAR > GOREE > MBAMBARA'."""
        parts, z = [], self
        while z is not None:
            parts.append(z.nom)
            z = z.parent
        return " > ".join(reversed(parts))

    def descendants(self, niveau=None):
        """Toutes les zones sous celle-ci, éventuellement filtrées par niveau."""
        qs = Zone.objects.filter(code__startswith=f"{self.code}-")
        return qs.filter(niveau=niveau) if niveau else qs