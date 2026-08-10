# Migration to fix permission codes to use name instead of resource.action

from django.db import migrations, models


def fix_permission_codes(apps, schema_editor):
    """Update permission codes to use the name field value."""
    Permission = apps.get_model("authentication", "Permission")
    
    for permission in Permission.objects.all():
        # Update code to match the name field
        permission.code = permission.name
        permission.save(update_fields=['code'])


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0007_permission_code_non_nullable"),
    ]

    operations = [
        migrations.RunPython(fix_permission_codes, migrations.RunPython.noop),
    ]
