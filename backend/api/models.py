from django.db import models


class Requete(models.Model):
    """
    Historique et cache.

    Deux rôles :

      - HISTORIQUE affiché à l'utilisateur.
      - CACHE : une question déjà posée renvoie instantanément la même
        réponse. Décisif en démonstration, où le modèle met plusieurs
        dizaines de secondes sur une machine sans GPU — les questions
        préparées répondent alors sans délai, et de façon identique à
        chaque répétition.

    L'empreinte porte sur la question normalisée : casse, accents et
    ponctuation finale ne créent pas d'entrée distincte.
    """

    empreinte = models.CharField(max_length=64, db_index=True)
    question = models.TextField()

    statut = models.CharField(max_length=20)        # ok | refus | clarification
    reponse = models.JSONField()                    # la réponse complète

    duree_s = models.FloatField(null=True, blank=True)
    origine_plan = models.CharField(max_length=20, blank=True)  # modele | repli
    indicateur = models.CharField(max_length=60, blank=True)
    methode = models.CharField(max_length=30, blank=True)

    epingle = models.BooleanField(
        default=False,
        help_text="Question de démonstration : jamais purgée du cache.",
    )

    cree_le = models.DateTimeField(auto_now_add=True)
    utilisee = models.IntegerField(default=1)

    class Meta:
        ordering = ["-cree_le"]
        indexes = [
            models.Index(fields=["empreinte", "statut"]),
            models.Index(fields=["-cree_le"]),
        ]

    def __str__(self):
        return f"{self.question[:60]} [{self.statut}]"