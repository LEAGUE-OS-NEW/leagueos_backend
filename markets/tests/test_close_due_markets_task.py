from datetime import timedelta
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from authentication.models import Permission, Role, RolePermission
from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from markets.management.commands.bootstrap_market_automation_actor import (
    AUTOMATION_ACTOR_EMAIL,
    AUTOMATION_ROLE_NAME,
)
from markets.models import Market, MarketCategory, MarketScope
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.tasks import close_due_markets
from sports.models import Competition, Sport, SportingEvent


class CloseDueMarketsFixtureMixin:
    def setUp(self):
        super().setUp()
        self.now = timezone.now()

        approve_permission = PermissionFactory(
            name="approve_market", resource="market", action="approve"
        )
        manage_permission = PermissionFactory(
            name="manage_market", resource="market", action="manage"
        )
        approval_role = RoleFactory(name="Auto Close Approver", display_name="Auto Close Approver")
        operations_role = RoleFactory(
            name="Auto Close Operations", display_name="Auto Close Operations"
        )
        RolePermissionFactory(role=approval_role, permission=approve_permission)
        RolePermissionFactory(role=operations_role, permission=manage_permission)

        self.actor = UserFactory()
        self.outsider = UserFactory()
        UserRoleFactory(user=self.actor, role=approval_role)
        UserRoleFactory(user=self.outsider, role=operations_role)

        self.sport = Sport.objects.create(name="Auto Close Football", code="AUTO_CLOSE_FOOTBALL")
        self.category = MarketCategory.objects.create(name="Auto Close")
        self.competition = Competition.objects.create(
            sport=self.sport, name="Auto Close League", country_code="UG", is_verified=True
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Auto Close United v Auto Close City",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

    def create_open_market(self, *, closes_at, question="Auto close market?"):
        market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question=question,
            description="Auto close test.",
            rules="Official result applies.",
            resolution_source="Official result",
            resolution_criteria="Use final score.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=2),
            closes_at=self.now + timedelta(minutes=5),
            created_by=self.outsider,
            yes_label="Yes",
            no_label="No",
        )
        market = MarketLifecycleService.submit(
            market_id=market.id, actor=self.outsider, notes="Ready."
        )
        market = MarketLifecycleService.approve(
            market_id=market.id, actor=self.actor, notes="Approved."
        )
        market = MarketLifecycleService.open(market_id=market.id, actor=self.actor, notes="Opened.")
        # Simulate real time passing past closes_at while still OPEN — open()
        # itself refuses a closes_at already in the past, so this has to
        # happen after the fact, exactly like it does in production.
        Market.objects.filter(id=market.id).update(closes_at=closes_at)
        market.refresh_from_db()
        return market

    def bootstrap_automation_actor(self):
        call_command("bootstrap_market_automation_actor")
        return User.objects.get(email=AUTOMATION_ACTOR_EMAIL)


class CloseDueMarketsTaskTests(CloseDueMarketsFixtureMixin, TestCase):
    def test_overdue_open_market_is_closed_by_the_automation_actor(self):
        automation_actor = self.bootstrap_automation_actor()
        overdue = self.create_open_market(closes_at=self.now - timedelta(minutes=5))

        close_due_markets()

        overdue.refresh_from_db()
        self.assertEqual(overdue.status, Market.Status.CLOSED)
        transition = overdue.status_transitions.order_by("-created_at").first()
        self.assertEqual(transition.actor_id, automation_actor.id)
        self.assertEqual(transition.action, "CLOSE")

    def test_not_yet_due_market_is_left_untouched(self):
        self.bootstrap_automation_actor()
        not_due = self.create_open_market(closes_at=self.now + timedelta(hours=1))

        close_due_markets()

        not_due.refresh_from_db()
        self.assertEqual(not_due.status, Market.Status.OPEN)

    def test_one_failing_market_does_not_block_the_rest_of_the_sweep(self):
        self.bootstrap_automation_actor()
        first = self.create_open_market(
            closes_at=self.now - timedelta(minutes=5), question="First overdue market"
        )
        second = self.create_open_market(
            closes_at=self.now - timedelta(minutes=5), question="Second overdue market"
        )

        real_close = MarketLifecycleService.close
        calls = []

        def flaky_close(*, market_id, actor, notes):
            calls.append(market_id)
            if market_id == first.id:
                raise RuntimeError("simulated failure")
            return real_close(market_id=market_id, actor=actor, notes=notes)

        with patch(
            "markets.services.lifecycle_service.MarketLifecycleService.close",
            side_effect=flaky_close,
        ):
            close_due_markets()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(len(calls), 2)
        self.assertEqual(first.status, Market.Status.OPEN)
        self.assertEqual(second.status, Market.Status.CLOSED)

    def test_missing_automation_actor_logs_and_returns_without_raising(self):
        self.create_open_market(closes_at=self.now - timedelta(minutes=5))
        self.assertFalse(User.objects.filter(email=AUTOMATION_ACTOR_EMAIL).exists())

        close_due_markets()  # must not raise


class BootstrapMarketAutomationActorCommandTests(TestCase):
    def test_creates_a_scoped_non_superuser_account_with_unusable_password(self):
        call_command("seed_roles", verbosity=0)
        call_command("bootstrap_market_automation_actor")

        user = User.objects.get(email=AUTOMATION_ACTOR_EMAIL)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())

        role = Role.objects.get(name=AUTOMATION_ROLE_NAME)
        permission_codes = set(
            RolePermission.objects.filter(role=role).values_list("permission__code", flat=True)
        )
        self.assertEqual(permission_codes, {"approve_market"})

    def test_running_twice_is_idempotent(self):
        call_command("seed_roles", verbosity=0)
        call_command("bootstrap_market_automation_actor")
        call_command("bootstrap_market_automation_actor")

        self.assertEqual(User.objects.filter(email=AUTOMATION_ACTOR_EMAIL).count(), 1)
        self.assertEqual(Role.objects.filter(name=AUTOMATION_ROLE_NAME).count(), 1)
        role = Role.objects.get(name=AUTOMATION_ROLE_NAME)
        self.assertEqual(RolePermission.objects.filter(role=role).count(), 1)

    def test_requires_approve_market_permission_to_already_exist(self):
        self.assertFalse(Permission.objects.filter(code="approve_market").exists())
        with self.assertRaises(CommandError):
            call_command("bootstrap_market_automation_actor")
