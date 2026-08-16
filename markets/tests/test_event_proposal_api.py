from datetime import timedelta
from pathlib import Path

import yaml
from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from markets.models import (
    Market,
    MarketCategory,
    MarketEventGroup,
    MarketProposal,
    MarketProposalReview,
    MarketScope,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.event_service import MarketEventService
from sports.models import Sport, SportingEvent


class EventProposalAPITests(APITestCase):
    def setUp(self):
        self.now = timezone.now()
        self.user = UserFactory()
        self.other = UserFactory()
        self.manager = UserFactory()
        self.approver = UserFactory()
        manage = PermissionFactory(name="manage_market", resource="market", action="manage")
        approve = PermissionFactory(name="approve_market", resource="market", action="approve")
        manage_role = RoleFactory(name="Market Operations Admin")
        approve_role = RoleFactory(name="Market Approval Admin")
        RolePermissionFactory(role=manage_role, permission=manage)
        RolePermissionFactory(role=approve_role, permission=approve)
        UserRoleFactory(user=self.manager, role=manage_role)
        UserRoleFactory(user=self.approver, role=approve_role)
        self.sport = Sport.objects.create(name="Football", code="FOOTBALL")
        self.category = MarketCategory.objects.create(name="Match result")
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            name="KCCA v Vipers",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

    def proposal_payload(self, **overrides):
        values = {
            "question": "  Will KCCA win?  ",
            "category_id": str(self.category.id),
            "sporting_event_id": str(self.event.id),
            "proposed_closes_at": self.now + timedelta(days=1),
            "proposed_resolution_source": "Official result",
        }
        values.update(overrides)
        return values

    def test_public_events_are_paginated_and_only_published(self):
        draft = MarketEventService.create(
            actor=self.manager,
            title="Draft",
            slug="draft",
            event_type=MarketEventGroup.EventType.GENERAL_EVENT,
        )
        published = MarketEventService.create(
            actor=self.manager,
            title="Published",
            slug="published",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=self.event,
        )
        MarketEventService.publish(event_id=published.id, actor=self.approver)
        response = self.client.get(reverse("markets:market-event-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(published.id))
        self.assertNotIn("created_by", response.data["results"][0])
        self.assertNotEqual(response.data["results"][0]["id"], str(draft.id))

    def test_manager_can_attach_and_conflicting_group_returns_409(self):
        group = MarketEventService.create(
            actor=self.manager,
            title="Event",
            slug="event",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=self.event,
        )
        other_group = MarketEventService.create(
            actor=self.manager,
            title="Other",
            slug="other",
            event_type=MarketEventGroup.EventType.GENERAL_EVENT,
        )
        market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question="Will KCCA win?",
            status=Market.Status.DRAFT,
        )
        self.client.force_authenticate(self.manager)
        url = reverse("markets:admin-market-event-attach-market", kwargs={"event_id": group.id})
        self.assertEqual(self.client.post(url, {"market_id": market.id}).status_code, 200)
        self.assertEqual(self.client.post(url, {"market_id": market.id}).status_code, 200)
        conflict = self.client.post(
            reverse(
                "markets:admin-market-event-attach-market", kwargs={"event_id": other_group.id}
            ),
            {"market_id": market.id},
        )
        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)

    def test_participant_proposal_is_private_editable_and_withdrawable(self):
        self.assertEqual(
            self.client.post(
                reverse("markets:market-proposal-list-create"), self.proposal_payload()
            ).status_code,
            401,
        )
        self.client.force_authenticate(self.user)
        created = self.client.post(
            reverse("markets:market-proposal-list-create"), self.proposal_payload(), format="json"
        )
        self.assertEqual(created.status_code, 201, created.data)
        proposal = MarketProposal.objects.get()
        self.assertEqual(proposal.proposer, self.user)
        self.assertEqual(proposal.question, "Will KCCA win?")
        MarketProposal.objects.create(
            proposer=self.other,
            question="Other?",
            category=self.category,
            sporting_event=self.event,
            proposed_closes_at=self.now + timedelta(days=1),
        )
        listing = self.client.get(reverse("markets:market-proposal-list-create"))
        self.assertEqual(listing.data["count"], 1)
        self.assertNotIn("reviewed_by", created.data)
        withdrawn = self.client.post(
            reverse("markets:market-proposal-withdraw", kwargs={"proposal_id": proposal.id})
        )
        self.assertEqual(withdrawn.status_code, 200)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, MarketProposal.Status.WITHDRAWN)

    def test_approval_creates_one_draft_market_and_one_review_idempotently(self):
        self.client.force_authenticate(self.user)
        created = self.client.post(
            reverse("markets:market-proposal-list-create"),
            self.proposal_payload(question="Will there be over 2 goals?"),
            format="json",
        )
        proposal = MarketProposal.objects.get(id=created.data["id"])
        self.client.force_authenticate(self.approver)
        url = reverse("markets:admin-market-proposal-review", kwargs={"proposal_id": proposal.id})
        first = self.client.post(url, {"action": "APPROVE"}, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        second = self.client.post(url, {"action": "APPROVE"}, format="json")
        self.assertEqual(second.status_code, 200, second.data)
        proposal.refresh_from_db()
        self.assertEqual(proposal.approved_market.status, Market.Status.DRAFT)
        self.assertEqual(Market.objects.count(), 1)
        self.assertEqual(MarketProposalReview.objects.filter(action="APPROVE").count(), 1)
        self.assertIsNotNone(proposal.approved_market.event_group)

    def test_existing_exact_market_blocks_approval_with_stable_409(self):
        MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question="Will KCCA win?",
            status=Market.Status.DRAFT,
        )
        self.client.force_authenticate(self.user)
        created = self.client.post(
            reverse("markets:market-proposal-list-create"), self.proposal_payload(), format="json"
        )
        self.assertEqual(
            created.data["duplicate_status"], MarketProposal.DuplicateStatus.POSSIBLE_DUPLICATE
        )
        self.client.force_authenticate(self.approver)
        response = self.client.post(
            reverse(
                "markets:admin-market-proposal-review", kwargs={"proposal_id": created.data["id"]}
            ),
            {"action": "APPROVE"},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "market_proposal_duplicate_conflict")

    def create_group(self, *, title="Event", slug="event-api", sporting=True):
        return MarketEventService.create(
            actor=self.manager,
            title=title,
            slug=slug,
            event_type=(
                MarketEventGroup.EventType.SPORTING_EVENT
                if sporting
                else MarketEventGroup.EventType.GENERAL_EVENT
            ),
            sporting_event=self.event if sporting else None,
            category=self.category,
        )

    def create_market(self, *, group=None, question="Will KCCA win?", status_value=None):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            event_group=group,
            question=question,
            status=status_value or Market.Status.DRAFT,
        )

    def test_seeded_event_role_permission_matrix_and_draft_visibility(self):
        group = self.create_group()
        market = self.create_market()
        list_url = reverse("markets:admin-market-event-list-create")
        detail_url = reverse("markets:admin-market-event-detail", kwargs={"event_id": group.id})
        attach_url = reverse(
            "markets:admin-market-event-attach-market", kwargs={"event_id": group.id}
        )

        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        created = self.client.post(
            list_url,
            {
                "title": "Created by operations",
                "slug": "created-by-operations",
                "event_type": MarketEventGroup.EventType.GENERAL_EVENT,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(
            self.client.patch(detail_url, {"description": "Edited"}, format="json").status_code,
            200,
        )
        self.assertEqual(
            self.client.post(attach_url, {"market_id": market.id}, format="json").status_code,
            200,
        )
        self.assertEqual(
            self.client.delete(
                reverse(
                    "markets:admin-market-event-detach-market",
                    kwargs={"event_id": group.id, "market_id": market.id},
                )
            ).status_code,
            204,
        )

        self.client.force_authenticate(self.approver)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.assertEqual(self.client.post(list_url, {}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(detail_url, {}, format="json").status_code, 403)
        self.assertEqual(
            self.client.post(attach_url, {"market_id": market.id}, format="json").status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                reverse(
                    "markets:admin-market-event-detach-market",
                    kwargs={"event_id": group.id, "market_id": market.id},
                )
            ).status_code,
            403,
        )
        publish = reverse("markets:admin-market-event-publish", kwargs={"event_id": group.id})
        archive = reverse("markets:admin-market-event-archive", kwargs={"event_id": group.id})
        self.assertEqual(self.client.post(publish).status_code, 200)
        self.assertEqual(self.client.post(archive).status_code, 200)

        self.client.force_authenticate(self.user)
        for url in (list_url, detail_url, publish, archive, attach_url):
            self.assertEqual(
                (
                    self.client.get(url).status_code
                    if url in (list_url, detail_url)
                    else self.client.post(url, {}).status_code
                ),
                403,
            )

    def test_public_event_filters_order_counts_visibility_and_non_mutation(self):
        group = self.create_group(title="Beta", slug="beta")
        MarketEventService.publish(event_id=group.id, actor=self.approver)
        statuses = list(Market.Status.values)
        for index, market_status in enumerate(statuses):
            market = self.create_market(
                group=group,
                question=f"Status market {index}?",
            )
            Market.objects.filter(pk=market.pk).update(status=market_status)
        group.refresh_from_db()
        before = group.updated_at
        listing = self.client.get(
            reverse("markets:market-event-list"),
            {
                "event_type": MarketEventGroup.EventType.SPORTING_EVENT,
                "category_id": self.category.id,
                "sporting_event_id": self.event.id,
                "scheduled_from": self.now,
                "scheduled_to": self.now + timedelta(days=3),
                "search": "Beta",
            },
        )
        self.assertEqual(listing.status_code, 200, listing.data)
        item = listing.data["results"][0]
        public_statuses = {
            Market.Status.APPROVED,
            Market.Status.OPEN,
            Market.Status.SUSPENDED,
            Market.Status.CLOSED,
            Market.Status.RESOLVED,
            Market.Status.VOIDED,
        }
        self.assertEqual(item["market_count"], len(public_statuses))
        self.assertEqual(item["open_market_count"], 1)
        detail = self.client.get(
            reverse("markets:market-event-detail", kwargs={"event_id": group.id})
        )
        self.assertEqual(detail.status_code, 200)
        markets = self.client.get(
            reverse("markets:market-event-market-list", kwargs={"event_id": group.id}),
            {"page_size": 2},
        )
        self.assertEqual(markets.status_code, 200)
        self.assertEqual(markets.data["count"], len(public_statuses))
        self.assertEqual(len(markets.data["results"]), 2)
        group.refresh_from_db()
        self.assertEqual(group.updated_at, before)

        archived = MarketEventService.create(
            actor=self.manager,
            title="Archived",
            slug="archived-api",
            event_type=MarketEventGroup.EventType.GENERAL_EVENT,
        )
        MarketEventService.publish(event_id=archived.id, actor=self.approver)
        MarketEventService.archive(event_id=archived.id, actor=self.approver)
        self.assertEqual(
            self.client.get(
                reverse("markets:market-event-detail", kwargs={"event_id": archived.id})
            ).status_code,
            404,
        )

    def test_event_error_and_missing_object_matrix(self):
        group = self.create_group()
        self.client.force_authenticate(self.approver)
        publish_url = reverse("markets:admin-market-event-publish", kwargs={"event_id": group.id})
        self.assertEqual(self.client.post(publish_url).status_code, 200)
        repeated = self.client.post(publish_url)
        self.assertEqual(repeated.status_code, 400)
        self.assertEqual(repeated.data["code"][0], "market_event_invalid_transition")
        self.client.force_authenticate(self.manager)
        frozen = self.client.patch(
            reverse("markets:admin-market-event-detail", kwargs={"event_id": group.id}),
            {"event_type": MarketEventGroup.EventType.GENERAL_EVENT},
            format="json",
        )
        self.assertEqual(frozen.status_code, 400)
        self.assertEqual(frozen.data["code"][0], "market_event_identity_frozen")
        missing = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(
            self.client.get(
                reverse("markets:admin-market-event-detail", kwargs={"event_id": missing})
            ).status_code,
            404,
        )
        attach_missing_event = self.client.post(
            reverse("markets:admin-market-event-attach-market", kwargs={"event_id": missing}),
            {"market_id": self.create_market().id},
        )
        self.assertEqual(attach_missing_event.status_code, 404)
        attach_missing_market = self.client.post(
            reverse("markets:admin-market-event-attach-market", kwargs={"event_id": group.id}),
            {"market_id": missing},
        )
        self.assertEqual(attach_missing_market.status_code, 404)

    def test_participant_proposal_detail_patch_privacy_and_validation(self):
        self.client.force_authenticate(self.user)
        created = self.client.post(
            reverse("markets:market-proposal-list-create"), self.proposal_payload(), format="json"
        )
        proposal_id = created.data["id"]
        detail_url = reverse("markets:market-proposal-detail", kwargs={"proposal_id": proposal_id})
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        patched = self.client.patch(detail_url, {"question": "Updated question?"}, format="json")
        self.assertEqual(patched.status_code, 200, patched.data)
        unsupported = self.client.post(
            reverse("markets:market-proposal-list-create"),
            self.proposal_payload(scope_type=MarketScope.COMPETITION),
            format="json",
        )
        self.assertEqual(unsupported.status_code, 400)
        empty = self.client.post(
            reverse("markets:market-proposal-list-create"),
            self.proposal_payload(question="...!!!"),
            format="json",
        )
        self.assertEqual(empty.status_code, 400)
        missing_close = self.client.post(
            reverse("markets:market-proposal-list-create"),
            self.proposal_payload(proposed_closes_at=None),
            format="json",
        )
        self.assertEqual(missing_close.status_code, 400)
        proposal = MarketProposal.objects.get(pk=proposal_id)
        proposal.status = MarketProposal.Status.UNDER_REVIEW
        proposal.save(update_fields=["status"])
        self.client.force_authenticate(self.user)
        not_editable = self.client.patch(detail_url, {"question": "Cannot edit?"}, format="json")
        self.assertEqual(not_editable.status_code, 400)
        not_withdrawable = self.client.post(
            reverse("markets:market-proposal-withdraw", kwargs={"proposal_id": proposal_id})
        )
        self.assertEqual(not_withdrawable.status_code, 400)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_admin_proposal_lists_filters_reviews_privacy_and_method_restrictions(self):
        self.client.force_authenticate(self.user)
        created = self.client.post(
            reverse("markets:market-proposal-list-create"),
            self.proposal_payload(question="Review API?"),
            format="json",
        )
        proposal_id = created.data["id"]
        review_url = reverse(
            "markets:admin-market-proposal-review", kwargs={"proposal_id": proposal_id}
        )
        reviews_url = reverse(
            "markets:admin-market-proposal-review-list", kwargs={"proposal_id": proposal_id}
        )
        self.client.force_authenticate(self.manager)
        listing = self.client.get(
            reverse("markets:admin-market-proposal-list"),
            {
                "status": MarketProposal.Status.SUBMITTED,
                "duplicate_status": MarketProposal.DuplicateStatus.CLEAR,
                "category_id": self.category.id,
                "sporting_event_id": self.event.id,
                "proposer_id": self.user.id,
                "submitted_from": self.now - timedelta(days=1),
                "submitted_to": self.now + timedelta(days=1),
                "search": "Review",
            },
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual(
            self.client.get(
                reverse("markets:admin-market-proposal-detail", kwargs={"proposal_id": proposal_id})
            ).status_code,
            200,
        )
        started = self.client.post(review_url, {"action": "START_REVIEW"}, format="json")
        self.assertEqual(started.status_code, 200)
        self.assertEqual(self.client.post(review_url, {"action": "APPROVE"}).status_code, 403)
        self.client.force_authenticate(self.approver)
        reason_required = self.client.post(review_url, {"action": "REJECT"}, format="json")
        self.assertEqual(reason_required.status_code, 400)
        rejected = self.client.post(
            review_url, {"action": "REJECT", "reason": "Not suitable"}, format="json"
        )
        self.assertEqual(rejected.status_code, 200, rejected.data)
        history = self.client.get(reviews_url)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data["count"], 2)
        row = history.data["results"][0]
        self.assertIn("actor_id", row)
        self.assertIn("reason", row)
        self.assertNotIn("email", row)
        self.assertNotIn("username", row)
        for method in (self.client.patch, self.client.put, self.client.delete):
            self.assertEqual(method(review_url, {}, format="json").status_code, 405)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(reviews_url).status_code, 403)

    def test_public_event_ordering_is_schedule_nulls_last_title_then_uuid(self):
        timestamp = self.now + timedelta(days=4)
        values = [
            ("Past", "order-past", self.now - timedelta(days=1)),
            ("Zulu", "order-zulu", timestamp),
            ("Alpha", "order-alpha-one", timestamp),
            ("Alpha", "order-alpha-two", timestamp),
            ("Null", "order-null", None),
        ]
        groups = []
        for title, slug, scheduled_at in values:
            group = MarketEventService.create(
                actor=self.manager,
                title=title,
                slug=slug,
                event_type=MarketEventGroup.EventType.GENERAL_EVENT,
                scheduled_at=scheduled_at,
            )
            MarketEventService.publish(event_id=group.id, actor=self.approver)
            groups.append(group)
        response = self.client.get(reverse("markets:market-event-list"), {"page_size": 100})
        actual = [row["id"] for row in response.data["results"]]
        identical = sorted([groups[2], groups[3]], key=lambda group: str(group.id))
        expected = [
            str(groups[0].id),
            *(str(group.id) for group in identical),
            str(groups[1].id),
            str(groups[4].id),
        ]
        self.assertEqual(actual, expected)

    def test_openapi_path_enums_pagination_conflicts_and_legacy_paths(self):
        schema = yaml.safe_load((Path(settings.BASE_DIR) / "schema.yaml").read_text())
        paths = schema["paths"]
        required = {
            "/api/v1/market-events/",
            "/api/v1/market-events/{event_id}/",
            "/api/v1/market-events/{event_id}/markets/",
            "/api/v1/market-admin/events/",
            "/api/v1/market-admin/events/{event_id}/",
            "/api/v1/market-admin/events/{event_id}/publish/",
            "/api/v1/market-admin/events/{event_id}/archive/",
            "/api/v1/market-admin/events/{event_id}/markets/",
            "/api/v1/market-admin/events/{event_id}/markets/{market_id}/",
            "/api/v1/markets/proposals/",
            "/api/v1/markets/proposals/{proposal_id}/",
            "/api/v1/markets/proposals/{proposal_id}/withdraw/",
            "/api/v1/market-admin/proposals/",
            "/api/v1/market-admin/proposals/{proposal_id}/",
            "/api/v1/market-admin/proposals/{proposal_id}/review/",
            "/api/v1/market-admin/proposals/{proposal_id}/reviews/",
        }
        self.assertTrue(required <= set(paths))
        legacy = {
            "/api/v1/markets/",
            "/api/v1/markets/{market_id}/",
            "/api/v1/market-admin/markets/",
            "/api/v1/markets/responsible-participation/",
            "/api/v1/markets/responsible-participation/cooling-off/",
            "/api/v1/markets/responsible-participation/self-exclusion/",
        }
        self.assertTrue(legacy <= set(paths))
        for path in (
            "/api/v1/market-events/",
            "/api/v1/market-events/{event_id}/markets/",
            "/api/v1/market-admin/events/",
            "/api/v1/markets/proposals/",
            "/api/v1/market-admin/proposals/",
            "/api/v1/market-admin/proposals/{proposal_id}/reviews/",
        ):
            parameters = paths[path]["get"].get("parameters", [])
            self.assertIn("page", {parameter.get("name") for parameter in parameters})
        attach_responses = paths["/api/v1/market-admin/events/{event_id}/markets/"]["post"][
            "responses"
        ]
        approval_responses = paths["/api/v1/market-admin/proposals/{proposal_id}/review/"]["post"][
            "responses"
        ]
        self.assertIn("409", attach_responses)
        self.assertIn("409", approval_responses)
        review_methods = set(paths["/api/v1/market-admin/proposals/{proposal_id}/reviews/"])
        self.assertEqual(review_methods, {"get"})
        schemas = schema["components"]["schemas"]
        scope_enum = schemas["MarketProposalParticipantScopeTypeEnum"]
        action_enum = schemas["MarketProposalReviewActionEnum"]
        self.assertEqual(scope_enum["enum"], ["EVENT"])
        self.assertEqual(
            set(action_enum["enum"]),
            {"START_REVIEW", "APPROVE", "REJECT", "MARK_DUPLICATE"},
        )

    def test_volume_query_ceilings_are_constant(self):
        groups = []
        for index in range(5):
            group = MarketEventService.create(
                actor=self.manager,
                title=f"Volume {index}",
                slug=f"volume-{index}",
                event_type=MarketEventGroup.EventType.GENERAL_EVENT,
                scheduled_at=self.now + timedelta(days=index),
            )
            MarketEventService.publish(event_id=group.id, actor=self.approver)
            groups.append(group)
        markets = []
        for index in range(5):
            market = self.create_market(question=f"Public volume {index}?")
            Market.objects.filter(pk=market.pk).update(status=Market.Status.OPEN)
            markets.append(market)
            grouped = MarketCatalogService.create_market(
                sport=self.sport,
                category=self.category,
                scope_type=MarketScope.CUSTOM,
                sporting_event=None,
                custom_subject=f"Volume topic {index}",
                event_group=groups[0],
                question=f"Grouped public volume {index}?",
                status=Market.Status.DRAFT,
            )
            Market.objects.filter(pk=grouped.pk).update(status=Market.Status.OPEN)
        proposals = [
            MarketProposal.objects.create(
                proposer=self.user,
                question=f"Proposal volume {index}?",
                category=self.category,
                sporting_event=self.event,
                proposed_closes_at=self.now + timedelta(days=1),
            )
            for index in range(5)
        ]
        for index in range(5):
            MarketProposalReview.objects.create(
                proposal=proposals[0],
                actor=self.manager,
                action=MarketProposalReview.Action.START_REVIEW,
                previous_status=MarketProposal.Status.SUBMITTED,
                new_status=MarketProposal.Status.UNDER_REVIEW,
                reason=f"Review {index}",
            )
        duplicate = MarketProposal.objects.create(
            proposer=self.user,
            question="Proposal volume 1?",
            category=self.category,
            sporting_event=self.event,
            proposed_closes_at=self.now + timedelta(days=1),
            duplicate_status=MarketProposal.DuplicateStatus.POSSIBLE_DUPLICATE,
        )

        public_requests = {
            "public event list": (reverse("markets:market-event-list"), 4),
            "public event detail": (
                reverse("markets:market-event-detail", kwargs={"event_id": groups[0].id}),
                3,
            ),
            "event market list": (
                reverse("markets:market-event-market-list", kwargs={"event_id": groups[0].id}),
                6,
            ),
            "public market list with event summaries": (reverse("markets:market-list"), 7),
        }
        authenticated_requests = {
            "participant proposal list": (
                self.user,
                reverse("markets:market-proposal-list-create"),
                5,
            ),
            "participant proposal detail": (
                self.user,
                reverse("markets:market-proposal-detail", kwargs={"proposal_id": proposals[0].id}),
                3,
            ),
            "duplicate_candidates": (
                self.user,
                reverse("markets:market-proposal-detail", kwargs={"proposal_id": duplicate.id}),
                6,
            ),
            "admin event list": (
                self.manager,
                reverse("markets:admin-market-event-list-create"),
                5,
            ),
            "admin event detail": (
                self.manager,
                reverse("markets:admin-market-event-detail", kwargs={"event_id": groups[0].id}),
                4,
            ),
            "admin proposal list": (
                self.manager,
                reverse("markets:admin-market-proposal-list"),
                5,
            ),
            "admin proposal detail": (
                self.manager,
                reverse(
                    "markets:admin-market-proposal-detail",
                    kwargs={"proposal_id": proposals[0].id},
                ),
                4,
            ),
            "admin review history": (
                self.manager,
                reverse(
                    "markets:admin-market-proposal-review-list",
                    kwargs={"proposal_id": proposals[0].id},
                ),
                4,
            ),
        }

        counts = {}
        self.client.force_authenticate(None)
        for label, (url, ceiling) in public_requests.items():
            self.client.get(url)
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            counts[label] = len(captured)
            self.assertLessEqual(counts[label], ceiling, label)
        for label, (user, url, ceiling) in authenticated_requests.items():
            self.client.force_authenticate(user)
            self.client.get(url)
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            counts[label] = len(captured)
            self.assertLessEqual(counts[label], ceiling, label)

        for index in range(5, 10):
            group = MarketEventService.create(
                actor=self.manager,
                title=f"Volume {index}",
                slug=f"volume-{index}",
                event_type=MarketEventGroup.EventType.GENERAL_EVENT,
            )
            MarketEventService.publish(event_id=group.id, actor=self.approver)
            MarketProposal.objects.create(
                proposer=self.user,
                question=f"Proposal volume {index}?",
                category=self.category,
                sporting_event=self.event,
                proposed_closes_at=self.now + timedelta(days=1),
            )
        self.client.force_authenticate(None)
        for label, (url, _) in public_requests.items():
            with CaptureQueriesContext(connection) as captured:
                self.client.get(url)
            self.assertEqual(len(captured), counts[label], label)
        for label, (user, url, _) in authenticated_requests.items():
            self.client.force_authenticate(user)
            with CaptureQueriesContext(connection) as captured:
                self.client.get(url)
            self.assertEqual(len(captured), counts[label], label)
