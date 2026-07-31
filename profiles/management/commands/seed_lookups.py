"""Management command to seed lookup tables with initial data."""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

from profiles.models import Country, Gender, Language, Timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Seed lookup tables (countries, languages, timezones, genders) with initial data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force seeding even if data exists.",
        )

    def handle(self, *args, **options):
        from django.db import transaction

        try:
            with transaction.atomic():
                self.stdout.write("Seeding lookup tables...")

                countries = [
                    ("Uganda", "UG"),
                    ("Kenya", "KE"),
                    ("Tanzania", "TZ"),
                    ("Rwanda", "RW"),
                    ("Burundi", "BI"),
                    ("United States", "US"),
                    ("United Kingdom", "GB"),
                    ("Canada", "CA"),
                    ("Australia", "AU"),
                    ("Germany", "DE"),
                    ("France", "FR"),
                    ("Spain", "ES"),
                    ("Italy", "IT"),
                    ("Netherlands", "NL"),
                    ("Brazil", "BR"),
                    ("Argentina", "AR"),
                    ("Mexico", "MX"),
                    ("Japan", "JP"),
                    ("South Korea", "KR"),
                    ("India", "IN"),
                    ("China", "CN"),
                    ("South Africa", "ZA"),
                    ("Nigeria", "NG"),
                    ("Egypt", "EG"),
                    ("Ghana", "GH"),
                ]

                created_countries = 0
                for name, iso_code in countries:
                    _, created = Country.objects.get_or_create(
                        iso_code=iso_code,
                        defaults={"name": name, "is_active": True},
                    )
                    if created:
                        created_countries += 1

                total_countries = len(countries)
                self.stdout.write(
                    self.style.SUCCESS(f"Countries: {created_countries} created, "
                                      f"{total_countries - created_countries} existed.")
                )

                languages = [
                    ("English", "en"),
                    ("Afrikaans", "af"),
                    ("Arabic", "ar"),
                    ("Chinese", "zh"),
                    ("Dutch", "nl"),
                    ("French", "fr"),
                    ("German", "de"),
                    ("Hindi", "hi"),
                    ("Italian", "it"),
                    ("Japanese", "ja"),
                    ("Korean", "ko"),
                    ("Portuguese", "pt"),
                    ("Russian", "ru"),
                    ("Spanish", "es"),
                    ("Swahili", "sw"),
                ]

                created_languages = 0
                for name, code in languages:
                    _, created = Language.objects.get_or_create(
                        code=code,
                        defaults={"name": name, "is_active": True},
                    )
                    if created:
                        created_languages += 1

                total_languages = len(languages)
                self.stdout.write(
                    self.style.SUCCESS(f"Languages: {created_languages} created, "
                                      f"{total_languages - created_languages} existed.")
                )

                timezones = [
                    ("Africa/Kampala", "+03:00"),
                    ("Africa/Nairobi", "+03:00"),
                    ("Africa/Dar_es_Salaam", "+03:00"),
                    ("Africa/Kigali", "+02:00"),
                    ("Africa/Bujumbura", "+02:00"),
                    ("America/New_York", "-05:00"),
                    ("America/Los_Angeles", "-08:00"),
                    ("America/Chicago", "-06:00"),
                    ("Europe/London", "+00:00"),
                    ("Europe/Paris", "+01:00"),
                    ("Europe/Berlin", "+01:00"),
                    ("Asia/Tokyo", "+09:00"),
                    ("Asia/Shanghai", "+08:00"),
                    ("Asia/Kolkata", "+05:30"),
                    ("Australia/Sydney", "+10:00"),
                ]

                created_timezones = 0
                for tz_name, utc_offset in timezones:
                    _, created = Timezone.objects.get_or_create(
                        timezone_name=tz_name,
                        defaults={"utc_offset": utc_offset, "is_active": True},
                    )
                    if created:
                        created_timezones += 1

                total_timezones = len(timezones)
                self.stdout.write(
                    self.style.SUCCESS(f"Timezones: {created_timezones} created, "
                                      f"{total_timezones - created_timezones} existed.")
                )

                genders = [
                    ("Male", "M"),
                    ("Female", "F"),
                    ("Non-binary", "NB"),
                    ("Prefer not to say", "PNTS"),
                ]

                created_genders = 0
                for name, code in genders:
                    _, created = Gender.objects.get_or_create(
                        code=code,
                        defaults={"name": name, "is_active": True},
                    )
                    if created:
                        created_genders += 1

                total_genders = len(genders)
                self.stdout.write(
                    self.style.SUCCESS(f"Genders: {created_genders} created, "
                                      f"{total_genders - created_genders} existed.")
                )

        except Exception as e:
            raise CommandError(f"Failed to seed lookup tables: {e}") from e

        self.stdout.write(self.style.SUCCESS("Lookup tables seeded successfully."))