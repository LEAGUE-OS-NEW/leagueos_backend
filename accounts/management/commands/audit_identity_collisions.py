from django.core.management.base import BaseCommand, CommandError

from accounts.identity_audit import audit_identity_rows
from accounts.models import User


class Command(BaseCommand):
    help = "Read-only pre-deployment audit for identity data that blocks migration 0008."

    def handle(self, *args, **options):
        rows = User.objects.order_by("id").values("id", "email", "username", "phone_number")
        result = audit_identity_rows(rows)
        categories = (
            ("case-insensitive email collisions", result.email_collisions),
            ("case-insensitive username collisions", result.username_collisions),
            ("phone normalization collisions", result.phone_collisions),
            ("invalid phones", result.invalid_phones),
            ("noncanonical phones", result.noncanonical_phones),
            ("blank phone strings (must be NULL)", result.blank_phone_strings),
            ("blank/NULL emails", result.blank_emails),
            ("blank/NULL usernames", result.blank_usernames),
        )
        for label, findings in categories:
            self.stdout.write(f"{label}: {findings or 'none'}")
        if result.blocking:
            raise CommandError(
                "Identity audit failed. Resolve the listed records under an approved identity "
                "policy, then rerun this command before deploying migration 0008."
            )
        self.stdout.write(self.style.SUCCESS("Identity audit passed; no blocking records found."))
