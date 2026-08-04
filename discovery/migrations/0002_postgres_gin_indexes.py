"""Add PostgreSQL GIN indexes for full-text search.

This migration is safe on all backends.  The GIN indexes are only
created when the connected database is PostgreSQL; on other backends
(SQLite, MySQL) the operation is a no-op.

The indexes are built on concatenated ``search_vector`` expressions for
the canonical searchable entities:
- clubs
- players (athletes)
- competitions
- fixtures (sporting events)
"""

from __future__ import annotations

from django.db import connection, migrations


def _create_gin_indexes(apps, schema_editor):
    """Create GIN indexes only on PostgreSQL."""
    if connection.vendor != "postgresql":
        return

    statements = [
        (
            "discovery_club_search_vector_idx",
            "profiles_club",
            "to_tsvector('english', coalesce(name, '') || ' ' || coalesce(slug, ''))",
        ),
        (
            "discovery_player_search_vector_idx",
            "sports_participant",
            (
                "to_tsvector('english', coalesce(name, '') || ' ' || "
                "coalesce(short_name, '') || ' ' || coalesce(slug, ''))"
            ),
        ),
        (
            "discovery_competition_search_vector_idx",
            "sports_competition",
            "to_tsvector('english', coalesce(name, '') || ' ' || coalesce(slug, ''))",
        ),
        (
            "discovery_fixture_search_vector_idx",
            "sports_sportingevent",
            "to_tsvector('english', coalesce(name, '') || ' ' || coalesce(venue, ''))",
        ),
    ]

    with schema_editor.connection.cursor() as cursor:
        for index_name, table, expression in statements:
            cursor.execute(f"CREATE INDEX {index_name} ON {table} USING gin ({expression});")


def _drop_gin_indexes(apps, schema_editor):
    """Drop GIN indexes only on PostgreSQL."""
    if connection.vendor != "postgresql":
        return

    index_names = [
        "discovery_club_search_vector_idx",
        "discovery_player_search_vector_idx",
        "discovery_competition_search_vector_idx",
        "discovery_fixture_search_vector_idx",
    ]

    with schema_editor.connection.cursor() as cursor:
        for index_name in index_names:
            cursor.execute(f"DROP INDEX IF EXISTS {index_name};")


class Migration(migrations.Migration):
    """Vendor-guarded GIN index migration for full-text search."""

    dependencies = [
        ("discovery", "0001_initial"),
        ("profiles", "0001_initial"),
        ("sports", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            code=_create_gin_indexes,
            reverse_code=_drop_gin_indexes,
        ),
    ]
