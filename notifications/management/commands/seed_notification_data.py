"""Management command to seed notification categories and channels.

Seeds the database with default notification categories and channels
from configuration. Can be run multiple times safely (idempotent).
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from notifications.models import (
    NotificationCategory,
    NotificationChannel,
    NotificationChannelCapability,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Seed notification categories and channels."""

    help = "Seed notification categories and channels with default data"

    def handle(self, *args, **options):
        """Execute the command."""
        self.stdout.write("Seeding notification data...")

        # Seed channels first (categories may reference channels)
        self.seed_channels()

        # Seed categories
        self.seed_categories()

        # Seed capabilities
        self.seed_capabilities()

        self.stdout.write(self.style.SUCCESS("Successfully seeded notification data"))

    def seed_channels(self):
        """Seed notification channels."""
        channels_data = [
            {
                "code": "EMAIL",
                "name": "Email",
                "description": "Email notifications",
                "provider": "smtp",
                "display_order": 1,
            },
            {
                "code": "PUSH",
                "name": "Push Notification",
                "description": "Push notifications to mobile devices",
                "provider": "fcm",
                "display_order": 2,
            },
            {
                "code": "IN_APP",
                "name": "In-App Notification",
                "description": "In-app notifications",
                "provider": "internal",
                "display_order": 3,
            },
        ]

        for channel_data in channels_data:
            channel, created = NotificationChannel.objects.get_or_create(
                code=channel_data["code"],
                defaults={
                    "name": channel_data["name"],
                    "description": channel_data["description"],
                    "provider": channel_data["provider"],
                    "display_order": channel_data["display_order"],
                    "is_active": True,
                },
            )
            if created:
                self.stdout.write(f"  Created channel: {channel.code}")
            else:
                self.stdout.write(f"  Channel exists: {channel.code}")

    def seed_categories(self):
        """Seed notification categories."""
        categories_data = [
            # Sports & Fixtures
            {
                "code": "FIXTURES",
                "name": "Fixtures",
                "description": "Match fixtures and schedules",
                "mandatory": False,
                "default_enabled": True,
                "priority": 10,
                "display_order": 1,
            },
            {
                "code": "LIVE_MATCH_UPDATES",
                "name": "Live Match Updates",
                "description": "Real-time match updates",
                "mandatory": False,
                "default_enabled": True,
                "priority": 20,
                "display_order": 2,
            },
            {
                "code": "MATCH_RESULTS",
                "name": "Match Results",
                "description": "Match results and scores",
                "mandatory": False,
                "default_enabled": True,
                "priority": 30,
                "display_order": 3,
            },
            # Fantasy
            {
                "code": "FANTASY_COMPETITIONS",
                "name": "Fantasy Competitions",
                "description": "Fantasy league and competition updates",
                "mandatory": False,
                "default_enabled": True,
                "priority": 40,
                "display_order": 4,
            },
            {
                "code": "FANTASY_TEAM_UPDATES",
                "name": "Fantasy Team Updates",
                "description": "Updates about your fantasy team",
                "mandatory": False,
                "default_enabled": True,
                "priority": 50,
                "display_order": 5,
            },
            # Betting
            {
                "code": "BETTING_MARKETS",
                "name": "Betting Markets",
                "description": "New betting markets and odds",
                "mandatory": False,
                "default_enabled": False,
                "priority": 60,
                "display_order": 6,
            },
            {
                "code": "BETTING_RESULTS",
                "name": "Betting Results",
                "description": "Betting results and winnings",
                "mandatory": False,
                "default_enabled": True,
                "priority": 70,
                "display_order": 7,
            },
            # News
            {
                "code": "CLUB_NEWS",
                "name": "Club News",
                "description": "News from your favorite clubs",
                "mandatory": False,
                "default_enabled": True,
                "priority": 80,
                "display_order": 8,
            },
            {
                "code": "COMPETITION_NEWS",
                "name": "Competition News",
                "description": "News from competitions",
                "mandatory": False,
                "default_enabled": True,
                "priority": 90,
                "display_order": 9,
            },
            # Membership & Tickets
            {
                "code": "MEMBERSHIP_UPDATES",
                "name": "Membership Updates",
                "description": "Membership status and benefits",
                "mandatory": False,
                "default_enabled": True,
                "priority": 100,
                "display_order": 10,
            },
            {
                "code": "TICKET_PURCHASES",
                "name": "Ticket Purchases",
                "description": "Ticket purchase confirmations",
                "mandatory": True,
                "default_enabled": True,
                "priority": 110,
                "display_order": 11,
            },
            {
                "code": "TICKET_REMINDERS",
                "name": "Ticket Reminders",
                "description": "Reminders before events",
                "mandatory": False,
                "default_enabled": True,
                "priority": 120,
                "display_order": 12,
            },
            # Merchandise & Payments
            {
                "code": "MERCHANDISE_ORDERS",
                "name": "Merchandise Orders",
                "description": "Merchandise order updates",
                "mandatory": False,
                "default_enabled": True,
                "priority": 130,
                "display_order": 13,
            },
            {
                "code": "PAYMENTS",
                "name": "Payments",
                "description": "Payment confirmations and receipts",
                "mandatory": True,
                "default_enabled": True,
                "priority": 140,
                "display_order": 14,
            },
            # Marketing
            {
                "code": "PROMOTIONAL_CAMPAIGNS",
                "name": "Promotional Campaigns",
                "description": "Promotional offers and campaigns",
                "mandatory": False,
                "default_enabled": False,
                "priority": 150,
                "display_order": 15,
            },
            {
                "code": "PRODUCT_UPDATES",
                "name": "Product Updates",
                "description": "Product features and updates",
                "mandatory": False,
                "default_enabled": True,
                "priority": 160,
                "display_order": 16,
            },
            {
                "code": "FEATURE_ANNOUNCEMENTS",
                "name": "Feature Announcements",
                "description": "New feature announcements",
                "mandatory": False,
                "default_enabled": True,
                "priority": 170,
                "display_order": 17,
            },
            # Security & Compliance (MANDATORY)
            {
                "code": "ACCOUNT_ACTIVITY",
                "name": "Account Activity",
                "description": "Account activity notifications",
                "mandatory": True,
                "default_enabled": True,
                "priority": 1000,
                "display_order": 100,
            },
            {
                "code": "LOGIN_ALERTS",
                "name": "Login Alerts",
                "description": "New login notifications",
                "mandatory": True,
                "default_enabled": True,
                "priority": 1010,
                "display_order": 101,
            },
            {
                "code": "PASSWORD_CHANGES",
                "name": "Password Changes",
                "description": "Password change notifications",
                "mandatory": True,
                "default_enabled": True,
                "priority": 1020,
                "display_order": 102,
            },
            {
                "code": "SECURITY_ALERTS",
                "name": "Security Alerts",
                "description": "Security-related notifications",
                "mandatory": True,
                "default_enabled": True,
                "priority": 1030,
                "display_order": 103,
            },
            {
                "code": "COMPLIANCE_UPDATES",
                "name": "Compliance Updates",
                "description": "Compliance and regulatory updates",
                "mandatory": True,
                "default_enabled": True,
                "priority": 1040,
                "display_order": 104,
            },
            {
                "code": "PRIVACY_POLICY_UPDATES",
                "name": "Privacy Policy Updates",
                "description": "Privacy policy changes",
                "mandatory": True,
                "default_enabled": True,
                "priority": 1050,
                "display_order": 105,
            },
            {
                "code": "TERMS_OF_SERVICE_UPDATES",
                "name": "Terms of Service Updates",
                "description": "Terms of service changes",
                "mandatory": True,
                "default_enabled": True,
                "priority": 1060,
                "display_order": 106,
            },
        ]

        categories_data.extend(
            [
                {
                    "code": "MARKET_ORDERS",
                    "name": "Market Orders",
                    "description": "Order status updates",
                    "mandatory": False,
                    "default_enabled": True,
                    "priority": 200,
                    "display_order": 20,
                },
                {
                    "code": "MARKET_TRADES",
                    "name": "Market Trades",
                    "description": "Trade execution updates",
                    "mandatory": False,
                    "default_enabled": True,
                    "priority": 210,
                    "display_order": 21,
                },
                {
                    "code": "MARKET_RESULTS",
                    "name": "Market Results",
                    "description": "Result and dispute updates",
                    "mandatory": False,
                    "default_enabled": True,
                    "priority": 220,
                    "display_order": 22,
                },
                {
                    "code": "MARKET_SETTLEMENTS",
                    "name": "Market Settlements",
                    "description": "Settlement and refund updates",
                    "mandatory": True,
                    "default_enabled": True,
                    "priority": 1100,
                    "display_order": 110,
                },
                {
                    "code": "MARKET_DISPUTES",
                    "name": "Market Disputes",
                    "description": "Market dispute updates",
                    "mandatory": True,
                    "default_enabled": True,
                    "priority": 1110,
                    "display_order": 111,
                },
                {
                    "code": "MARKET_COMPLIANCE",
                    "name": "Market Compliance",
                    "description": "Verification and participation compliance",
                    "mandatory": True,
                    "default_enabled": True,
                    "priority": 1120,
                    "display_order": 112,
                },
                {
                    "code": "MARKET_OPERATIONAL_ALERTS",
                    "name": "Market Operational Alerts",
                    "description": "Permission-scoped operational alerts",
                    "mandatory": True,
                    "default_enabled": True,
                    "priority": 1130,
                    "display_order": 113,
                },
            ]
        )

        for category_data in categories_data:
            category, created = NotificationCategory.objects.get_or_create(
                code=category_data["code"],
                defaults={
                    "name": category_data["name"],
                    "description": category_data["description"],
                    "mandatory": category_data["mandatory"],
                    "default_enabled": category_data["default_enabled"],
                    "priority": category_data["priority"],
                    "display_order": category_data["display_order"],
                    "is_active": True,
                },
            )
            if created:
                self.stdout.write(f"  Created category: {category.code}")
            else:
                self.stdout.write(f"  Category exists: {category.code}")

    def seed_capabilities(self):
        """Seed channel capabilities."""
        # Get channels
        try:
            email_channel = NotificationChannel.objects.get(code="EMAIL")
            push_channel = NotificationChannel.objects.get(code="PUSH")
            in_app_channel = NotificationChannel.objects.get(code="IN_APP")
        except NotificationChannel.DoesNotExist:
            self.stderr.write("  Channels not found. Run seed_channels first.")
            return

        capabilities_data = [
            # Email capabilities
            {
                "channel": email_channel,
                "capability": "send",
                "is_supported": True,
            },
            {
                "channel": email_channel,
                "capability": "rich_content",
                "is_supported": True,
            },
            {
                "channel": email_channel,
                "capability": "attachments",
                "is_supported": True,
            },
            # Push capabilities
            {
                "channel": push_channel,
                "capability": "send",
                "is_supported": True,
            },
            {
                "channel": push_channel,
                "capability": "rich_content",
                "is_supported": True,
            },
            {
                "channel": push_channel,
                "capability": "deep_link",
                "is_supported": True,
            },
            # In-App capabilities
            {
                "channel": in_app_channel,
                "capability": "send",
                "is_supported": True,
            },
            {
                "channel": in_app_channel,
                "capability": "rich_content",
                "is_supported": True,
            },
            {
                "channel": in_app_channel,
                "capability": "persistent",
                "is_supported": True,
            },
        ]

        for cap_data in capabilities_data:
            capability, created = NotificationChannelCapability.objects.get_or_create(
                channel=cap_data["channel"],
                capability=cap_data["capability"],
                defaults={"is_supported": cap_data["is_supported"]},
            )
            if created:
                self.stdout.write(
                    f"  Created capability: {capability.channel.code} - {capability.capability}"
                )
