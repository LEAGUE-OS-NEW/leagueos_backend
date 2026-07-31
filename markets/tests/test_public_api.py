from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from markets.models import (
    Market,
    MarketCategory,
    MarketScope,
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


class PublicMarketAPITests(APITestCase):
    def setUp(self):
        self.now = timezone.now()

        self.football = Sport.objects.create(
            name="Football",
            code="FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Match Result",
            description="Binary match-result markets.",
        )
        self.inactive_category = MarketCategory.objects.create(
            name="Archived Markets",
            is_active=False,
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
            country_code="UG",
            is_verified=True,
        )
        self.vipers = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="Vipers SC",
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

        self.open_market = MarketCatalogService.create_market(
            sport=self.football,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question="Will KCCA FC beat Vipers SC?",
            description="Match result market.",
            status=Market.Status.OPEN,
            opens_at=self.now,
            closes_at=self.now + timedelta(days=1),
            is_featured=True,
            yes_label="KCCA FC",
            no_label="Vipers SC or Draw",
        )

        self.closed_market = MarketCatalogService.create_market(
            sport=self.football,
            category=self.category,
            scope_type=MarketScope.PARTICIPANT,
            sporting_event=self.event,
            participant=self.kcca,
            question="Will KCCA FC score first?",
            status=Market.Status.CLOSED,
            opens_at=self.now - timedelta(days=2),
            closes_at=self.now - timedelta(days=1),
        )

        self.draft_market = MarketCatalogService.create_market(
            sport=self.football,
            category=self.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Uganda football",
            question=("Will a Ugandan club reach " "a continental final?"),
            status=Market.Status.DRAFT,
        )

    def test_market_list_defaults_to_open_markets(self):
        response = self.client.get(
            reverse("markets:market-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["count"],
            1,
        )
        self.assertEqual(
            response.data["results"][0]["id"],
            str(self.open_market.id),
        )

    def test_market_list_can_filter_public_status(self):
        response = self.client.get(
            reverse("markets:market-list"),
            {
                "status": Market.Status.CLOSED,
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["count"],
            1,
        )
        self.assertEqual(
            response.data["results"][0]["id"],
            str(self.closed_market.id),
        )

    def test_market_list_supports_catalog_filters(self):
        response = self.client.get(
            reverse("markets:market-list"),
            {
                "sport": str(self.football.id),
                "category": str(self.category.id),
                "scope_type": MarketScope.EVENT,
                "is_featured": "true",
                "search": "KCCA",
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["count"],
            1,
        )
        self.assertEqual(
            response.data["results"][0]["id"],
            str(self.open_market.id),
        )

    def test_market_detail_contains_subject_and_outcomes(self):
        response = self.client.get(
            reverse(
                "markets:market-detail",
                kwargs={
                    "market_id": self.open_market.id,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["sporting_event"]["id"],
            str(self.event.id),
        )
        self.assertEqual(
            [outcome["side"] for outcome in response.data["outcomes"]],
            [
                "YES",
                "NO",
            ],
        )
        self.assertEqual(
            [outcome["label"] for outcome in response.data["outcomes"]],
            [
                "KCCA FC",
                "Vipers SC or Draw",
            ],
        )

    def test_draft_market_is_not_publicly_accessible(self):
        response = self.client.get(
            reverse(
                "markets:market-detail",
                kwargs={
                    "market_id": self.draft_market.id,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_category_list_excludes_inactive_categories(self):
        response = self.client.get(
            reverse("markets:category-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        category_ids = {item["id"] for item in response.data["results"]}

        self.assertIn(
            str(self.category.id),
            category_ids,
        )
        self.assertNotIn(
            str(self.inactive_category.id),
            category_ids,
        )
