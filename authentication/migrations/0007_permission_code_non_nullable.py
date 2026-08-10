# Migration to make permission code non-nullable and unique

from django.db import migrations, models


def fix_duplicate_codes(apps, schema_editor):
    """Fix duplicate permission codes before adding unique constraint."""
    Permission = apps.get_model("authentication", "Permission")

    # Find and fix any duplicate codes
    from django.db.models import Count

    duplicates = Permission.objects.values("code").annotate(count=Count("id")).filter(count__gt=1)

    for dup in duplicates:
        code = dup["code"]
        perms = Permission.objects.filter(code=code).order_by("id")
        # Keep the first one, rename the rest
        for i, perm in enumerate(perms[1:], start=1):
            # Use name as the code since names should be unique
            perm.code = perm.name
            perm.save()


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0006_populate_permission_data"),
    ]

    operations = [
        migrations.RunPython(fix_duplicate_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="permission",
            name="code",
            field=models.CharField(max_length=100, unique=True),
        ),
    ]
