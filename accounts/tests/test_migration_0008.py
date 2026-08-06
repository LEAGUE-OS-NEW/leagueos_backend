import importlib
import inspect

from django.db import migrations
from django.test import SimpleTestCase


class IdentityMigrationStructureTests(SimpleTestCase):
    def setUp(self):
        self.module = importlib.import_module(
            "accounts.migrations.0008_alter_user_phone_number_and_more"
        )

    def test_frozen_audit_is_the_first_operation(self):
        operation = self.module.Migration.operations[0]
        self.assertIsInstance(operation, migrations.RunPython)
        self.assertIs(operation.code, self.module.fail_on_unsafe_identity_data)
        self.assertIs(operation.reverse_code, migrations.RunPython.noop)

    def test_frozen_audit_does_not_import_mutable_project_code(self):
        source = inspect.getsource(self.module)
        self.assertNotIn("from accounts", source)
        self.assertNotIn("import accounts", source)
        self.assertIn('apps.get_model("accounts", "User")', source)
