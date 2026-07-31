from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from markets.models import (
    Market,
    MarketCategory,
    MarketOutcome,
    MarketScope,
    MarketTemplate,
)
from markets.services.catalog_service import (
    MarketCatalogService,
)
from sports.models import (
    Competition,
    Participant,
    Sport,
    SportingEvent,
)


class MarketCatalogueModelTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

        self.football = Sport.objects.create(
            name="Football",
            code="FOOTBALL",
        )
        self.rugby = Sport.objects.create(
            name="Rugby",
            code="RUGBY",
        )

        self.competition = Competition.objects.create(
            sport=self.football,
            name="Uganda Premier League",
            country_code="UG",
            is_verified=True,
        )

        self.kcca = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="KCCA FC",
            short_name="KCCA",
            country_code="UG",
            is_verified=True,
        )
        self.vipers = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="Vipers SC",
            short_name="Vipers",
            country_code="UG",
            is_verified=True,
        )

        self.event = SportingEvent.objects.create(
            sport=self.football,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="KCCA FC vs Vipers SC",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

        self.category = MarketCategory.objects.create(
            name="Match Result",
            description="Binary match-result markets.",
        )

    def market_values(self, **overrides):
        values = {
            "sport": self.football,
            "category": self.category,
            "scope_type": MarketScope.EVENT,
            "sporting_event": self.event,
            "question": "Will KCCA FC beat Vipers SC?",
            "opens_at": self.now,
            "closes_at": self.now + timedelta(days=1),
        }
        values.update(overrides)

        return values

    def test_category_normalizes_slug(self):
        self.assertEqual(
            self.category.slug,
            "match-result",
        )

    def test_template_normalizes_code_and_slug(self):
        template = MarketTemplate.objects.create(
            category=self.category,
            sport=self.football,
            scope_type=MarketScope.EVENT,
            name="Match Winner",
            code="match_winner",
            question_template=("Will {participant} win {event}?"),
        )

        self.assertEqual(
            template.code,
            "MATCH_WINNER",
        )
        self.assertEqual(
            template.slug,
            "match-winner",
        )

    def test_event_market_requires_sporting_event(self):
        market = Market(
            **self.market_values(
                sporting_event=None,
            )
        )

        with self.assertRaises(ValidationError):
            market.full_clean()

    def test_custom_market_requires_custom_subject(self):
        market = Market(
            **self.market_values(
                scope_type=MarketScope.CUSTOM,
                sporting_event=None,
                custom_subject="",
            )
        )

        with self.assertRaises(ValidationError):
            market.full_clean()

    def test_participant_market_supports_event_context(self):
        market = Market(
            **self.market_values(
                scope_type=MarketScope.PARTICIPANT,
                participant=self.kcca,
            )
        )

        market.full_clean()

        self.assertEqual(
            market.participant,
            self.kcca,
        )
        self.assertEqual(
            market.sporting_event,
            self.event,
        )

    def test_market_rejects_target_from_another_sport(self):
        market = Market(
            **self.market_values(
                sport=self.rugby,
            )
        )

        with self.assertRaises(ValidationError) as context:
            market.full_clean()

        self.assertIn(
            "sporting_event",
            context.exception.message_dict,
        )

    def test_market_rejects_template_scope_mismatch(self):
        template = MarketTemplate.objects.create(
            category=self.category,
            sport=self.football,
            scope_type=MarketScope.COMPETITION,
            name="Competition Winner",
            code="competition_winner",
            question_template=("Will {participant} win {competition}?"),
        )

        market = Market(
            **self.market_values(
                template=template,
            )
        )

        with self.assertRaises(ValidationError) as context:
            market.full_clean()

        self.assertIn(
            "template",
            context.exception.message_dict,
        )

    def test_published_event_market_requires_verified_event(self):
        unverified_event = SportingEvent.objects.create(
            sport=self.football,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Unverified match",
            starts_at=self.now + timedelta(days=3),
        )

        market = Market(
            **self.market_values(
                sporting_event=unverified_event,
                status=Market.Status.PENDING_APPROVAL,
            )
        )

        with self.assertRaises(ValidationError) as context:
            market.full_clean()

        self.assertIn(
            "sporting_event",
            context.exception.message_dict,
        )

    def test_market_rejects_invalid_trading_window(self):
        market = Market(
            **self.market_values(
                opens_at=self.now + timedelta(days=2),
                closes_at=self.now + timedelta(days=1),
            )
        )

        with self.assertRaises(ValidationError) as context:
            market.full_clean()

        self.assertIn(
            "closes_at",
            context.exception.message_dict,
        )

    def test_catalog_service_creates_two_outcomes(self):
        market = MarketCatalogService.create_market(
            **self.market_values(),
        )

        outcomes = list(market.outcomes.order_by("position"))

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(
            [outcome.side for outcome in outcomes],
            [
                MarketOutcome.Side.YES,
                MarketOutcome.Side.NO,
            ],
        )
        self.assertEqual(
            [outcome.position for outcome in outcomes],
            [1, 2],
        )
        self.assertTrue(
            market.has_complete_outcomes,
        )

    def test_catalog_service_supports_custom_labels(self):
        market = MarketCatalogService.create_market(
            **self.market_values(),
            yes_label="KCCA FC",
            no_label="Vipers SC or Draw",
        )

        self.assertEqual(
            list(
                market.outcomes.order_by(
                    "position",
                ).values_list(
                    "label",
                    flat=True,
                )
            ),
            [
                "KCCA FC",
                "Vipers SC or Draw",
            ],
        )

    def test_invalid_outcome_rolls_back_entire_market(self):
        with self.assertRaises(ValidationError):
            MarketCatalogService.create_market(
                **self.market_values(),
                no_label="",
            )

        self.assertEqual(
            Market.objects.count(),
            0,
        )
        self.assertEqual(
            MarketOutcome.objects.count(),
            0,
        )

    def test_duplicate_outcome_position_is_blocked(self):
        market = MarketCatalogService.create_market(
            **self.market_values(),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketOutcome.objects.create(
                    market=market,
                    side=MarketOutcome.Side.NO,
                    position=1,
                    label="Duplicate position",
                )

    def test_outcome_side_must_match_position(self):
        outcome = MarketOutcome(
            market=Market(
                **self.market_values(),
            ),
            side=MarketOutcome.Side.NO,
            position=1,
            label="No",
        )

        with self.assertRaises(ValidationError):
            outcome.full_clean()
