"""Management command to seed initial dashboard data."""

from django.core.management.base import BaseCommand

from dashboard.models import DashboardModule, DashboardWidget, NavigationMenu


class Command(BaseCommand):
    """Seed initial dashboard configuration data."""

    help = "Seeds dashboard modules, widgets, and navigation menus"

    def handle(self, *args, **options):
        """Execute the command."""
        self.stdout.write("Seeding dashboard data...")

        # Create dashboard modules
        modules_data = [
            {
                "code": "profile",
                "name": "User Profile",
                "description": "User profile information and preferences",
                "display_order": 1,
                "icon": "user",
                "route": "/profile",
                "enabled": True,
                "cache_timeout": 300,
            },
            {
                "code": "notifications",
                "name": "Notifications",
                "description": "Recent notifications and alerts",
                "display_order": 2,
                "icon": "bell",
                "route": "/notifications",
                "enabled": True,
                "cache_timeout": 60,
            },
            {
                "code": "favourites",
                "name": "Favourite Clubs",
                "description": "Your favourite clubs and teams",
                "display_order": 3,
                "icon": "heart",
                "route": "/favourites",
                "enabled": True,
                "cache_timeout": 300,
            },
            {
                "code": "fixtures",
                "name": "Fixtures",
                "description": "Upcoming matches and fixtures",
                "display_order": 4,
                "icon": "calendar",
                "route": "/fixtures",
                "enabled": True,
                "cache_timeout": 120,
            },
            {
                "code": "markets",
                "name": "Betting Markets",
                "description": "Featured betting markets",
                "display_order": 5,
                "icon": "trending-up",
                "route": "/markets",
                "enabled": True,
                "cache_timeout": 180,
            },
            {
                "code": "wallet",
                "name": "Wallet",
                "description": "Wallet balance and transactions",
                "display_order": 6,
                "icon": "credit-card",
                "route": "/wallet",
                "enabled": True,
                "cache_timeout": 300,
            },
        ]

        modules = {}
        for module_data in modules_data:
            module, created = DashboardModule.objects.get_or_create(
                code=module_data["code"],
                defaults=module_data,
            )
            modules[module_data["code"]] = module
            if created:
                self.stdout.write(f"  Created module: {module.name}")

        # Create widgets
        widgets_data = [
            {
                "module": modules["profile"],
                "code": "user_summary",
                "title": "User Summary",
                "description": "Displays user name, avatar, and verification status",
                "display_order": 1,
                "cache_timeout": 300,
            },
            {
                "module": modules["notifications"],
                "code": "notification_summary",
                "title": "Notification Summary",
                "description": "Shows unread notification count and recent notifications",
                "display_order": 1,
                "cache_timeout": 60,
            },
            {
                "module": modules["favourites"],
                "code": "favourite_clubs",
                "title": "Favourite Clubs",
                "description": "List of user's favourite clubs",
                "display_order": 1,
                "cache_timeout": 300,
            },
            {
                "module": modules["fixtures"],
                "code": "upcoming_fixtures",
                "title": "Upcoming Fixtures",
                "description": "Next 10 upcoming fixtures for favourite teams",
                "display_order": 1,
                "cache_timeout": 120,
            },
            {
                "module": modules["markets"],
                "code": "featured_markets",
                "title": "Featured Markets",
                "description": "Featured betting markets",
                "display_order": 1,
                "cache_timeout": 180,
            },
            {
                "module": modules["wallet"],
                "code": "wallet_summary",
                "title": "Wallet Summary",
                "description": "Wallet balance and recent transactions",
                "display_order": 1,
                "cache_timeout": 300,
            },
        ]

        for widget_data in widgets_data:
            widget, created = DashboardWidget.objects.get_or_create(
                module=widget_data["module"],
                code=widget_data["code"],
                defaults=widget_data,
            )
            if created:
                self.stdout.write(f"  Created widget: {widget.title}")

        # Create navigation menus
        navigation_data = [
            {
                "name": "Dashboard",
                "route": "/dashboard",
                "icon": "home",
                "display_order": 1,
            },
            {
                "name": "Fixtures",
                "route": "/fixtures",
                "icon": "calendar",
                "display_order": 2,
            },
            {
                "name": "Markets",
                "route": "/markets",
                "icon": "trending-up",
                "display_order": 3,
            },
            {
                "name": "Favourites",
                "route": "/favourites",
                "icon": "heart",
                "display_order": 4,
            },
            {
                "name": "Notifications",
                "route": "/notifications",
                "icon": "bell",
                "display_order": 5,
            },
            {
                "name": "Wallet",
                "route": "/wallet",
                "icon": "credit-card",
                "display_order": 6,
            },
            {
                "name": "Profile",
                "route": "/profile",
                "icon": "user",
                "display_order": 7,
            },
        ]

        for nav_data in navigation_data:
            nav_item, created = NavigationMenu.objects.get_or_create(
                route=nav_data["route"],
                defaults=nav_data,
            )
            if created:
                self.stdout.write(f"  Created navigation: {nav_item.name}")

        self.stdout.write(self.style.SUCCESS("Dashboard data seeded successfully!"))
