from django.db import migrations

CODES = [
    ("platform.fantasy.manage", "Manage Fantasy", "manage"),
    ("platform.fantasy.competitions.manage", "Manage Fantasy Competitions", "manage_competitions"),
    ("platform.fantasy.players.manage", "Manage Fantasy Players", "manage_players"),
    ("platform.fantasy.scoring.manage", "Manage Fantasy Scoring", "manage_scoring"),
    ("platform.fantasy.gameweeks.finalize", "Finalize Fantasy Gameweeks", "finalize_gameweeks"),
]


def forwards(apps, schema_editor):
    Permission = apps.get_model("authentication", "Permission")
    Role = apps.get_model("authentication", "Role")
    RolePermission = apps.get_model("authentication", "RolePermission")
    permissions = []
    for code, name, action in CODES:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "resource": "fantasy",
                "action": action,
                "description": name,
                "category": "Fantasy",
                "scope": "PLATFORM",
                "active": True,
                "delegatable": True,
            },
        )
        permissions.append(permission)
    fantasy_admin, _ = Role.objects.get_or_create(
        name="Fantasy Admin",
        defaults={
            "display_name": "Fantasy Admin",
            "description": "Operates Fantasy competitions and scoring.",
            "dashboard_url": "/dashboard/admin/fantasy",
            "scope": "PLATFORM",
            "category": "Fantasy",
        },
    )
    for permission in permissions:
        RolePermission.objects.get_or_create(role=fantasy_admin, permission=permission)
    for role in Role.objects.filter(name__in=["Super Admin"]):
        for permission in permissions:
            RolePermission.objects.get_or_create(role=role, permission=permission)


def backwards(apps, schema_editor):
    apps.get_model("authentication", "Permission").objects.filter(
        code__in=[x[0] for x in CODES]
    ).delete()
    apps.get_model("authentication", "Role").objects.filter(name="Fantasy Admin").delete()


class Migration(migrations.Migration):
    dependencies = [("fantasy", "0001_initial"), ("authentication", "0008_fix_permission_codes")]
    operations = [migrations.RunPython(forwards, backwards)]
