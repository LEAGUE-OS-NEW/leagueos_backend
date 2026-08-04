"""Management command to seed system configuration and feature flags."""

from django.core.management.base import BaseCommand

from system.models import FeatureFlag, SystemConfiguration

FEATURE_FLAGS = [
    {
        "code": "ENABLE_SPORTS",
        "description": "Enable sports discovery and feeds.",
        "enabled": True,
        "rollout_percentage": 100,
    },
    {
        "code": "ENABLE_FANTASY",
        "description": "Enable fantasy league features.",
        "enabled": True,
        "rollout_percentage": 100,
    },
    {
        "code": "ENABLE_TICKETING",
        "description": "Enable ticketing features.",
        "enabled": True,
        "rollout_percentage": 100,
    },
    {
        "code": "ENABLE_MARKETS",
        "description": "Enable betting markets.",
        "enabled": True,
        "rollout_percentage": 100,
    },
    {
        "code": "ENABLE_WALLET",
        "description": "Enable wallet and payments.",
        "enabled": True,
        "rollout_percentage": 100,
    },
    {
        "code": "ENABLE_NOTIFICATIONS",
        "description": "Enable notifications.",
        "enabled": True,
        "rollout_percentage": 100,
    },
]

SYSTEM_CONFIG = [
    {
        "key": "PLATFORM_NAME",
        "value": {"value": "League OS"},
        "description": "Platform display name.",
        "is_public": True,
    },
    {
        "key": "SUPPORT_EMAIL",
        "value": {"value": "support@leagueos.com"},
        "description": "Customer support email address.",
        "is_public": True,
    },
    {
        "key": "DEFAULT_CURRENCY",
        "value": {"value": "UGX"},
        "description": "Default currency for financial operations.",
        "is_public": True,
    },
    {
        "key": "MINIMUM_DEPOSIT",
        "value": {"value": "1000"},
        "description": "Minimum deposit amount in default currency.",
        "is_public": True,
    },
    {
        "key": "MAXIMUM_DEPOSIT",
        "value": {"value": "10000000"},
        "description": "Maximum deposit amount in default currency.",
        "is_public": True,
    },
    {
        "key": "MINIMUM_WITHDRAWAL",
        "value": {"value": "5000"},
        "description": "Minimum withdrawal amount in default currency.",
        "is_public": True,
    },
    {
        "key": "MAXIMUM_WITHDRAWAL",
        "value": {"value": "5000000"},
        "description": "Maximum withdrawal amount in default currency.",
        "is_public": True,
    },
    {
        "key": "MAINTENANCE_MODE",
        "value": {"value": False},
        "description": "Enable maintenance mode for the platform.",
        "is_public": True,
    },
]


class Command(BaseCommand):
    help = "Seed feature flags and system configuration."

    def handle(self, *args, **options):
        self.stdout.write("Seeding feature flags and system configuration...")

        for flag_data in FEATURE_FLAGS:
            code = flag_data["code"]
            defaults = {k: v for k, v in flag_data.items() if k != "code"}
            flag, created = FeatureFlag.objects.get_or_create(code=code, defaults=defaults)
            self.stdout.write(
                f"  {'Created' if created else 'Found'} feature flag: {flag.code}"
            )

        for config_data in SYSTEM_CONFIG:
            key = config_data["key"]
            defaults = {k: v for k, v in config_data.items() if k != "key"}
            config, created = SystemConfiguration.objects.get_or_create(
                key=key, defaults=defaults
            )
            self.stdout.write(
                f"  {'Created' if created else 'Found'} config: {config.key}"
            )

        self.stdout.write(self.style.SUCCESS("System configuration seeded successfully."))