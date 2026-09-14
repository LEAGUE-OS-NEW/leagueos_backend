"""Data migration: insert the SPORTS_DATA_ADMIN SportsFeedProvider row.

This provider is used by the Sports Data & Statistics Admin statistics-entry
workflow to track each fixture's statistics save as a SportsFeedIngestion.
The row must exist before any Sports Data Admin can save statistics via the
POST /api/v1/admin/fixtures/<id>/player-statistics/ endpoint.

The migration is fully reversible: the reverse function deletes the row only
if it still exists, making migrate --fake and squash operations safe.
"""

from __future__ import annotations

from django.db import migrations

PROVIDER_CODE = "SPORTS_DATA_ADMIN"
PROVIDER_NAME = "Sports Data & Statistics Admin"


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
        ("discovery", "0007_merge_20260819_1858"),
    ]

    operations = [
        migrations.RunPython(create_provider, reverse_code=delete_provider),
    ]
