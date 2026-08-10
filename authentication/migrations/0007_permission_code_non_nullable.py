# Migration to make permission code non-nullable

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0006_populate_permission_data"),
    ]

    operations = [
        migrations.AlterField(
            model_name="permission",
            name="code",
            field=models.CharField(max_length=100, unique=True),
        ),
    ]
