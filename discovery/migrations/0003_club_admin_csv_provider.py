"""Data migration: insert the CLUB_ADMIN_CSV SportsFeedProvider row.

This provider is used by the Club Admin match-data CSV upload flow to track
each import as a SportsFeedIngestion.  The row must exist before any Club
Admin can upload a CSV file.

The migration is fully reversible: the ``reverse_func`` deletes the row
if it still exists, making ``migrate --fake`` and squash operations safe.
"""

from __future__ import annotations

from django.db import migrations

PROVIDER_CODE = "CLUB_ADMIN_CSV"
PROVIDER_NAME = "Club Admin CSV Upload"


def create_provider(apps, schema_editor):
    SportsFeedProvider = apps.get_model("discovery", "SportsFeedProvider")
    SportsFeedProvider.objects.get_or_create(
        code=PROVIDER_CODE,
        defaults={
            "name": PROVIDER_NAME,
            "base_url": "",
            "is_active": True,
        },
    )


def delete_provider(apps, schema_editor):
    SportsFeedProvider = apps.get_model("discovery", "SportsFeedProvider")
    SportsFeedProvider.objects.filter(code=PROVIDER_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0002_postgres_gin_indexes"),
    ]

    operations = [
        migrations.RunPython(create_provider, reverse_code=delete_provider),
    ]
