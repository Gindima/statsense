"""
Extensions PostgreSQL requises par StatSense AI.

  pg_trgm  : recherche du catalogue par similarité de trigrammes
  unaccent : pour que « départements » trouve « departements »
  btree_gin : index combinés sur JSON + colonnes classiques

À placer dans backend/catalog/migrations/0002_extensions.py
APRÈS avoir lancé `makemigrations` une première fois.
Ajustez `dependencies` au nom réel de votre migration initiale.
"""

from django.contrib.postgres.operations import (
    BtreeGinExtension,
    TrigramExtension,
    UnaccentExtension,
)
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        TrigramExtension(),
        UnaccentExtension(),
        BtreeGinExtension(),
    ]