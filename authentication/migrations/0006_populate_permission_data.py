# Migration to populate permission code, category, scope fields

from django.db import migrations, models


def populate_permission_data(apps, schema_editor):
    Permission = apps.get_model("authentication", "Permission")
    Role = apps.get_model("authentication", "Role")

    # Populate Permission fields
    for permission in Permission.objects.all():
        # Generate code from resource:action
        code = f"{permission.resource}.{permission.action}"
        permission.code = code
        permission.category = "General"
        permission.scope = "PLATFORM"
        permission.delegatable = True
        permission.active = True
        permission.save()

    # Populate Role fields based on names
    role_mappings = {
        "Super Admin": {"scope": "PLATFORM", "category": "Platform Administration"},
        "Platform Admin": {"scope": "PLATFORM", "category": "Platform Administration"},
        "Club Admin": {"scope": "CLUB", "category": "Club Administration"},
        "Club Staff": {"scope": "CLUB", "category": "Club Staff"},
        "Club Media Manager": {"scope": "CLUB", "category": "Club Staff"},
        "Club Support Staff": {"scope": "CLUB", "category": "Club Staff"},
        "Club Analytics/Reporting Staff": {"scope": "CLUB", "category": "Club Staff"},
    }

    for role in Role.objects.all():
        if role.name in role_mappings:
            role.scope = role_mappings[role.name]["scope"]
            role.category = role_mappings[role.name]["category"]
            role.save()


def reverse_populate(apps, schema_editor):
    Permission = apps.get_model("authentication", "Permission")
    Role = apps.get_model("authentication", "Role")

    for permission in Permission.objects.all():
        permission.code = None
        permission.category = None
        permission.scope = "PLATFORM"
        permission.delegatable = True
        permission.active = True
        permission.save()

    for role in Role.objects.all():
        role.category = None
        role.scope = "PLATFORM"
        role.save()


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0005_permission_active_permission_category_and_more"),
    ]

    operations = [
        migrations.RunPython(populate_permission_data, reverse_populate),
    ]
