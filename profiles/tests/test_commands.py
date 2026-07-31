"""Tests for profiles management commands."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from profiles.models import Country, Gender, Language, Timezone


@pytest.mark.django_db
class TestSeedLookups:
    def test_seed_lookups_command(self):
        """Test that the seed_lookups command runs successfully."""
        out = StringIO()
        call_command("seed_lookups", stdout=out)

        assert "Lookup tables seeded successfully." in out.getvalue()
        assert Country.objects.count() == 25
        assert Language.objects.count() == 15
        assert Timezone.objects.count() == 15
        assert Gender.objects.count() == 4

    def test_seed_lookups_command_idempotent(self):
        """Test that running the command multiple times does not create duplicates."""
        out = StringIO()
        call_command("seed_lookups", stdout=out)
        first_run_output = out.getvalue()

        assert "created, 0 existed." in first_run_output

        out = StringIO()
        call_command("seed_lookups", stdout=out)
        second_run_output = out.getvalue()

        assert "0 created" in second_run_output
        assert "existed." in second_run_output
        assert Country.objects.count() == 25