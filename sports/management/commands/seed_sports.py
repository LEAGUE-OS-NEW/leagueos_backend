from django.core.management.base import BaseCommand
from django.utils.text import slugify

from sports.models import Sport

INITIAL_SPORTS = [
    {
        "name": "Football",
        "code": "FOOTBALL",
    },
    {
        "name": "Rugby",
        "code": "RUGBY",
    },
    {
        "name": "Basketball",
        "code": "BASKETBALL",
    },
]


class Command(BaseCommand):
    help = "Seed the initial League OS sports catalogue"

    def handle(self, *args, **options):
        for sport_data in INITIAL_SPORTS:
            sport, created = Sport.objects.update_or_create(
                code=sport_data["code"],
                defaults={
                    "name": sport_data["name"],
                    "slug": slugify(
                        sport_data["name"],
                    ),
                    "is_active": True,
                },
            )

            action = "Created" if created else "Updated"

            self.stdout.write(f"{action} sport: {sport.name}")

        self.stdout.write(self.style.SUCCESS("Successfully seeded sports catalogue."))
