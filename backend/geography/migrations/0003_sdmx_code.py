"""
Ajoute Zone.sdmx_code — code géographique du catalogue standardisé ANSD.

Format hiérarchique : SN / SN-DK / SN-DK-PI. Distinct de geojson_id,
qui ne concerne que les régions et sert au rendu cartographique.

À placer dans backend/geography/migrations/
Ajustez `dependencies` au nom réel de votre migration initiale.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("geography", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="zone",
            name="sdmx_code",
            field=models.CharField(blank=True, db_index=True, default="",
                                   max_length=20),
        ),
    ]