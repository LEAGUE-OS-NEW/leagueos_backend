from django.core.management.base import BaseCommand

from markets.models import MarketCategory

INITIAL_MARKET_CATEGORIES = [
    {
        "name": "Match Result",
        "description": (
            "Binary match-result prediction markets " "resolved from the official sporting result."
        ),
        "display_order": 10,
    },
]


class Command(BaseCommand):
    help = "Seed the core League OS market catalogue"

    def handle(self, *args, **options):
        for category_data in INITIAL_MARKET_CATEGORIES:
            category, created = MarketCategory.objects.update_or_create(
                name=category_data["name"],
                defaults={
                    "description": category_data["description"],
                    "display_order": category_data["display_order"],
                    "is_active": True,
                },
            )

            action = "Created" if created else "Updated"

            self.stdout.write(f"{action} market category: " f"{category.name}")

        self.stdout.write(self.style.SUCCESS("Successfully seeded market catalogue."))
