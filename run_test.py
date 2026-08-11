#!/usr/bin/env python
"""Quick test script to verify the ClubFactory fix."""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DATABASE_URL", "sqlite:///db_test.sqlite3")

django.setup()

from django.test.runner import DiscoverRunner

runner = DiscoverRunner(verbosity=2)
old_db_config = runner.setup_databases()

try:
    from clubs.tests.factories import ClubWorkspaceFactory

    # Simulate the test fixture: club_workspace_factory(name="Club Workspace A")
            ws = ClubWorkspaceFactory(club__name="Club Workspace A")

    print("\n=== SUCCESS ===")
    print(f"Workspace: {ws}")
    print(f"Club name: {ws.club.name}")
    print(f"Club slug: {ws.club.slug}")
    print(f"Club is_active: {ws.club.is_active}")
    print(f"Has description field: {hasattr(ws.club, 'description')}")
    print(f"Club model fields: {[f.name for f in ws.club._meta.get_fields() if hasattr(f, 'name') and not f.auto_created]}")

except Exception as e:
    print(f"\n=== FAILED ===")
    print(f"Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
finally:
    runner.teardown_databases(old_db_config)
    print("\nDone.")
