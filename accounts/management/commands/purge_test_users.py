from django.contrib.admin.utils import NestedObjects
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError

from accounts.models import User


class Command(BaseCommand):
    help = "Safely inspect or purge explicitly named test users (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--email", action="append", required=True, dest="emails")
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument(
            "--allow-protected-operational-admins",
            action="store_true",
            help="Allow deletion of non-staff users holding an operational/admin role.",
        )

    def handle(self, *args, **options):
        emails = {email.strip() for email in options["emails"] if email.strip()}
        if not emails:
            raise CommandError("At least one non-blank --email value is required.")
        email_query = Q()
        for email in emails:
            email_query |= Q(email__iexact=email)
        users = list(User.objects.filter(email_query).order_by("email"))
        if not users:
            self.stdout.write("No matching users found.")
            return

        refused = []
        for user in users:
            roles = list(user.user_roles.values_list("role__name", flat=True))
            operational = any(
                any(term in role.lower() for term in ("admin", "operations", "owner"))
                for role in roles
            )
            collector = NestedObjects(using=DEFAULT_DB_ALIAS)
            collector.collect([user])
            summary = {
                model._meta.label: len(objects) for model, objects in collector.model_objs.items()
            }
            self.stdout.write(
                f"id={user.id} email={user.email} username={user.username} "
                f"verified={user.is_verified} active={user.is_active} staff={user.is_staff} "
                f"superuser={user.is_superuser} created={user.created_at.isoformat()} "
                f"related={summary}"
            )
            if user.is_staff or user.is_superuser:
                refused.append(f"{user.email} is staff or superuser")
            elif operational and not options["allow_protected_operational_admins"]:
                refused.append(f"{user.email} has a protected operational/admin role")

        if refused:
            raise CommandError("Refusing deletion: " + "; ".join(refused))
        if not options["confirm"]:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --confirm to delete."))
            return

        try:
            with transaction.atomic():
                for user in users:
                    user.delete()
        except ProtectedError as exc:
            raise CommandError(f"Deletion blocked by protected related objects: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Deleted {len(users)} user(s)."))
