#!/usr/bin/env python
"""Quick test script to verify the ClubFactory fix."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DATABASE_URL", "sqlite:///db_test.sqlite3")

django.setup()

from django.test.runner import DiscoverRunner

runner = DiscoverRunner(verbosity=0)
old_db_config = runner.setup_databases()

try:
    from clubs.tests.factories import ClubWorkspaceFactory

    ws = ClubWorkspaceFactory(club__name="Club Workspace A")

    print()
    print("=== SUCCESS ===")
    print(f"Workspace: {ws}")
    print(f"Club name: {ws.club.name}")
    print(f"Club slug: {ws.club.slug}")
    print(f"Club is_active: {ws.club.is_active}")
    print(f"Has description field: {hasattr(ws.club, 'description')}")
except Exception as e:
    print()
    print("=== FAILED ===")
    print(f"Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
finally:
    runner.teardown_databases(old_db_config)
    print()
    print("Done.")
