from django.contrib.postgres.fields import ArrayField
from django.db import models


class Frequence(models.TextChoices):
    PONCTUEL = "ponctuel", "Ponctuel"
    ANNUEL = "annuel", "Annuel"
    TRIMESTRIEL = "trimestriel", "Trimestriel"


class Comparaison(models.TextChoices):
    N_MOINS_1 = "n-1", "Année précédente"
    T_MOINS_4 = "t-4", "Glissement annuel (T vs T-4)"


class Source(models.Model):
    """Provenance d'un jeu de données. Affichée sous chaque résultat."""

    cle = models.SlugField(unique=True)            # "rgph2023"
    nom = models.CharField(max_length=200)
    url = models.URLField()
    plateforme = models.CharField(max_length=100)
    date_extraction = models.DateField()
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Indicateur(models.Model):
    """
    Couche sémantique : la SEULE chose que le modèle de langage voit.

    Aucune valeur chiffrée ici. Qwen reçoit ces métadonnées pour choisir
    un indicateur dans une liste fermée, ce qui rend l'hallucination
    d'indicateur structurellement impossible : un code absent de cette
    table est rejeté à la validation, avant tout calcul.
    """

    code = models.SlugField(unique=True, db_index=True)
    libelle = models.CharField(max_length=200)

    # Formulations attendues des utilisateurs. Déterminant pour le taux de
    # compréhension : à enrichir en continu depuis l'admin.
    synonymes = ArrayField(models.CharField(max_length=80), default=list)

    unite = models.CharField(max_length=40)

    # Ventilations autorisées. Toute dimension absente de cette liste est
    # rejetée : empêche « le PIB par sexe ».
    dimensions = ArrayField(models.CharField(max_length=40),
                            default=list, blank=True)

    # False pour un taux ou une moyenne : le moteur refuse alors la somme
    # entre zones et propose une moyenne pondérée.
    agregeable = models.BooleanField(default=True)

    # Niveau géographique le plus fin disponible. Empêche « le PIB de Thiès ».
    granularite_geo_min = models.CharField(max_length=20)

    frequence = models.CharField(max_length=20, choices=Frequence.choices)

    # Sur une série trimestrielle : t-4 obligatoire (saisonnalité).
    comparaison_defaut = models.CharField(
        max_length=10, choices=Comparaison.choices, blank=True, null=True
    )

    # Agrégats monétaires réels : "constants 2014".
    prix_base = models.CharField(max_length=40, blank=True)

    # Indicateur calculé : formule sur d'autres codes, jamais stocké.
    derive_de = models.CharField(max_length=200, blank=True)

    # Hiérarchie sectorielle du PIB : total | secteur | branche
    niveau_sectoriel = models.CharField(max_length=20, blank=True)
    secteur_parent = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sous_secteurs",
    )

    source = models.ForeignKey(Source, on_delete=models.PROTECT,
                               related_name="indicateurs")

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["granularite_geo_min"]),
            models.Index(fields=["frequence"]),
        ]

    def __str__(self):
        return f"{self.libelle} ({self.code})"

    @property
    def est_derive(self):
        return bool(self.derive_de)

    def fiche_pour_llm(self):
        """Fiche compacte injectée dans le prompt d'extraction. Aucun chiffre."""
        return {
            "code": self.code,
            "libelle": self.libelle,
            "synonymes": self.synonymes,
            "unite": self.unite,
            "dimensions": self.dimensions,
            "granularite_min": self.granularite_geo_min,
            "frequence": self.frequence,
        }


class Chargement(models.Model):
    """
    Trace d'ingestion. Permet à `seed --append` de sauter un fichier déjà
    chargé et de recharger un fichier modifié, sans jamais dupliquer.

    L'enregistrement n'est créé qu'APRÈS succès complet du fichier : une
    interruption en cours de route ne laisse aucun état incohérent.
    """

    fichier = models.CharField(max_length=200, unique=True)
    empreinte = models.CharField(max_length=64)          # sha256 du contenu
    lignes_lues = models.IntegerField(default=0)
    zones_creees = models.IntegerField(default=0)
    observations_creees = models.IntegerField(default=0)
    charge_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-charge_le"]

    def __str__(self):
        return f"{self.fichier} — {self.observations_creees} obs."