from django.core.management.base import BaseCommand

from markets.models import MarketCategory

INITIAL_MARKET_CATEGORIES = [
    {
        "name": "Match Result",
        "description": ("Markets predicting the result or winner " "of a match or sporting event."),
        "display_order": 10,
    },
    {
        "name": "Totals",
        "description": (
            "Over or under markets based on points, " "goals, tries, scores, or other totals."
        ),
        "display_order": 20,
    },
    {
        "name": "Handicap / Spread",
        "description": (
            "Markets applying a points, goals, or score " "handicap between participants."
        ),
        "display_order": 30,
    },
    {
        "name": "Correct Score / Margin",
        "description": ("Markets predicting an exact score, " "winning margin, or score range."),
        "display_order": 40,
    },
    {
        "name": "Player / Team Prop",
        "description": (
            "Markets based on a player or team's " "specific performance or statistic."
        ),
        "display_order": 50,
    },
    {
        "name": "Tournament / Season",
        "description": (
            "Markets covering season, competition, "
            "qualification, advancement, or title outcomes."
        ),
        "display_order": 60,
    },
    {
        "name": "Event / Occurrence",
        "description": ("Markets predicting whether a specific " "event or occurrence happens."),
        "display_order": 70,
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
