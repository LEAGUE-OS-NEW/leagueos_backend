from importlib import import_module
from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import migrations
from django.test import TestCase

from accounts.identity_audit import audit_identity_rows
from accounts.models import User


class IdentityAuditTests(TestCase):
    def test_reports_every_collision_category_without_writes(self):
        rows = [
            {
                "id": "1",
                "email": "Fan@Example.com",
                "username": "Fan",
                "phone_number": "+256772123456",
            },
            {
                "id": "2",
                "email": "fan@example.com",
                "username": "fan",
                "phone_number": "+256 772 123456",
            },
            {
                "id": "3",
                "email": "other@example.com",
                "username": "other",
                "phone_number": "invalid",
            },
            {"id": "4", "email": "", "username": "", "phone_number": ""},
        ]
        result = audit_identity_rows(rows)
        self.assertTrue(result.blocking)
        self.assertEqual(result.email_collisions, [["1", "2"]])
        self.assertEqual(result.username_collisions, [["1", "2"]])
        self.assertEqual(result.phone_collisions[0]["ids"], ["1", "2"])
        self.assertEqual(result.invalid_phones[0]["id"], "3")
        self.assertEqual(result.blank_phone_strings, ["4"])

    def test_command_passes_for_safe_data_and_is_read_only(self):
        user = User.objects.create_user(
            username="safe-user", email="safe@example.com", phone_number="+256772123456"
        )
        before = User.objects.filter(pk=user.pk).values().get()
        output = StringIO()
        call_command("audit_identity_collisions", stdout=output)
        after = User.objects.filter(pk=user.pk).values().get()
        self.assertEqual(before, after)
        self.assertIn("Identity audit passed", output.getvalue())

    def test_command_exits_nonzero_for_invalid_phone_and_masks_it(self):
        user = User.objects.create_user(
            username="legacy", email="legacy@example.com", phone_number="not-a-phone-1234"
        )
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("audit_identity_collisions", stdout=output)
        text = output.getvalue()
        self.assertNotIn("not-a-phone-1234", text)
        self.assertIn(str(user.id), text)

    def test_migration_audits_before_any_schema_change_and_fails_actionably(self):
        migration = import_module("accounts.migrations.0008_alter_user_phone_number_and_more")
        self.assertIsInstance(migration.Migration.operations[0], migrations.RunPython)
        rows = [
            {
                "id": "id-1",
                "email": "Fan@example.com",
                "username": "fan-one",
                "phone_number": None,
            },
            {
                "id": "id-2",
                "email": "fan@example.com",
                "username": "fan-two",
                "phone_number": None,
            },
        ]
        historical_user = SimpleNamespace(
            objects=SimpleNamespace(
                using=lambda _alias: SimpleNamespace(values=lambda *_fields: rows)
            )
        )
        apps = SimpleNamespace(get_model=lambda *_args: historical_user)
        schema_editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))
        with self.assertRaisesRegex(RuntimeError, "email collisions ids=.*id-1"):
            migration.fail_on_unsafe_identity_data(apps, schema_editor)
