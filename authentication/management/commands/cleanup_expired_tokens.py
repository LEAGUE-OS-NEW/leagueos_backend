from django.core.management.base import BaseCommand

from authentication.services.account_setup_service import AccountSetupService


class Command(BaseCommand):
    help = "Clean up expired account setup tokens and admin invitations"

    def handle(self, *args, **options):
        self.stdout.write("Cleaning up expired tokens...")

        setup_expired = AccountSetupService.expire_old_tokens()
        self.stdout.write(self.style.SUCCESS(f"Expired {setup_expired} account setup tokens"))
