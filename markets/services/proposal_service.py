import hashlib
import json
import re
import unicodedata

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from markets.models import (
    Market,
    MarketEventGroup,
    MarketProposal,
    MarketProposalReview,
    MarketScope,
)
from markets.services.catalog_service import MarketCatalogService
from sports.models import SportingEvent


def normalize_market_question(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\r\n.,!?;:'\"`()[]{}¿¡")


def canonical_context_key(*, sporting_event_id=None, event_group=None, event_group_id=None):
    if sporting_event_id:
        return f"sporting-event:{sporting_event_id}"
    if event_group is None and event_group_id:
        event_group = MarketEventGroup.objects.only("id", "sporting_event_id").get(
            id=event_group_id
        )
    if event_group is not None:
        if event_group.sporting_event_id:
            return f"sporting-event:{event_group.sporting_event_id}"
        return f"event-group:{event_group.id}"
    return ""


def build_duplicate_fingerprint(
    *, question, category_id, sporting_event_id=None, event_group_id=None, event_group=None
):
    payload = [
        normalize_market_question(question),
        str(category_id or ""),
        canonical_context_key(
            sporting_event_id=sporting_event_id,
            event_group_id=event_group_id,
            event_group=event_group,
        ),
    ]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def build_market_duplicate_fingerprint(market):
    return build_duplicate_fingerprint(
        question=market.question,
        category_id=market.category_id,
        sporting_event_id=market.sporting_event_id,
        event_group_id=market.event_group_id,
        event_group=getattr(market, "event_group", None),
    )


class MarketProposalDuplicateConflict(Exception):
    pass


class MarketProposalService:
    BLOCKING_STATUSES = (
        MarketProposal.Status.SUBMITTED,
        MarketProposal.Status.UNDER_REVIEW,
        MarketProposal.Status.APPROVED,
    )
    HISTORICAL_MARKET_FALLBACK_LIMIT = 200

    @classmethod
    def duplicate_candidates(cls, proposal):
        proposal_ids = list(
            MarketProposal.objects.filter(
                duplicate_fingerprint=proposal.duplicate_fingerprint,
                status__in=cls.BLOCKING_STATUSES,
            )
            .exclude(id=proposal.id)
            .values_list("id", "question")
        )
        markets = list(
            Market.objects.filter(
                duplicate_fingerprint=proposal.duplicate_fingerprint,
            )
            .exclude(status__in=[Market.Status.REJECTED, Market.Status.VOIDED])
            .values_list("id", "question")
        )
        # Nullable fingerprints avoid a historical rewrite. The fallback is one
        # bounded, scoped query (never N+1) for legacy rows only.
        legacy = Market.objects.filter(
            duplicate_fingerprint__isnull=True,
            category_id=proposal.category_id,
        ).exclude(status__in=[Market.Status.REJECTED, Market.Status.VOIDED])
        context = canonical_context_key(
            sporting_event_id=proposal.sporting_event_id,
            event_group=proposal.proposed_event_group,
        )
        if context.startswith("sporting-event:"):
            legacy = legacy.filter(sporting_event_id=context.split(":", 1)[1])
        else:
            legacy = legacy.filter(event_group_id=proposal.proposed_event_group_id)
        normalized = normalize_market_question(proposal.question)
        markets.extend(
            (pk, question)
            for pk, question in legacy.values_list("id", "question")[
                : cls.HISTORICAL_MARKET_FALLBACK_LIMIT
            ]
            if normalize_market_question(question) == normalized
        )
        return {"proposals": proposal_ids, "markets": markets}

    @classmethod
    def _refresh_duplicate_state(cls, proposal):
        proposal.duplicate_fingerprint = build_duplicate_fingerprint(
            question=proposal.question,
            category_id=proposal.category_id,
            sporting_event_id=proposal.sporting_event_id,
            event_group=proposal.proposed_event_group,
        )
        candidates = cls.duplicate_candidates(proposal)
        proposal.duplicate_status = (
            MarketProposal.DuplicateStatus.POSSIBLE_DUPLICATE
            if candidates["proposals"] or candidates["markets"]
            else MarketProposal.DuplicateStatus.CLEAR
        )
        proposal.duplicate_of_market = None
        proposal.duplicate_of_proposal = None

    @classmethod
    @transaction.atomic
    def submit(cls, *, proposer, **data):
        proposal = MarketProposal(proposer=proposer, **data)
        proposal.full_clean()
        proposal.save()
        cls._refresh_duplicate_state(proposal)
        proposal.save(
            update_fields=[
                "duplicate_status",
                "duplicate_fingerprint",
                "duplicate_of_market",
                "duplicate_of_proposal",
                "updated_at",
            ]
        )
        from notifications.services.operational_alert_service import OperationalAlertService

        OperationalAlertService.create(
            permissions=("manage_market",),
            event_type="MARKET_PROPOSAL_AWAITING_REVIEW",
            title="Market proposal awaiting review",
            message="A market proposal requires review.",
            source_key=f"market-proposal:{proposal.id}:submitted",
            data={"proposal_id": str(proposal.id)},
        )
        return proposal

    @classmethod
    @transaction.atomic
    def update(cls, *, proposal_id, proposer, **data):
        proposal = MarketProposal.objects.select_for_update().get(id=proposal_id, proposer=proposer)
        if proposal.status != MarketProposal.Status.SUBMITTED:
            raise ValidationError({"code": "market_proposal_not_editable"})
        for key, value in data.items():
            setattr(proposal, key, value)
        proposal.question = proposal.question.strip()
        proposal.full_clean()
        cls._refresh_duplicate_state(proposal)
        proposal.save()
        return proposal

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, proposal_id, proposer):
        proposal = MarketProposal.objects.select_for_update().get(id=proposal_id, proposer=proposer)
        if proposal.status != MarketProposal.Status.SUBMITTED:
            raise ValidationError({"code": "market_proposal_not_withdrawable"})
        proposal.status = MarketProposal.Status.WITHDRAWN
        proposal.withdrawn_at = timezone.now()
        proposal.save(update_fields=["status", "withdrawn_at", "updated_at"])
        return proposal

    @classmethod
    def _canonical_group(cls, proposal, actor):
        event = SportingEvent.objects.select_for_update().get(id=proposal.sporting_event_id)
        if proposal.proposed_event_group_id:
            return MarketEventGroup.objects.select_for_update().get(
                id=proposal.proposed_event_group_id, sporting_event=event
            )
        try:
            with transaction.atomic():
                group, _ = MarketEventGroup.objects.get_or_create(
                    sporting_event=event,
                    defaults={
                        "title": proposal.proposed_event_title or event.name,
                        "slug": f"sporting-event-{event.id}",
                        "event_type": MarketEventGroup.EventType.SPORTING_EVENT,
                        "category": proposal.category,
                        "scheduled_at": event.starts_at,
                        "created_by": actor,
                    },
                )
                return group
        except IntegrityError:
            return MarketEventGroup.objects.get(sporting_event=event)

    @classmethod
    def _validate_duplicate_target(cls, proposal, market, other):
        if bool(market) == bool(other):
            raise ValidationError({"code": "market_proposal_duplicate_target_exactly_one"})
        if other:
            if other.id == proposal.id:
                raise ValidationError({"code": "market_proposal_duplicate_target_self"})
            if other.status in (MarketProposal.Status.WITHDRAWN, MarketProposal.Status.REJECTED):
                raise ValidationError({"code": "market_proposal_duplicate_target_ineligible"})
            compatible = other.duplicate_fingerprint == proposal.duplicate_fingerprint
        else:
            compatible = (
                build_market_duplicate_fingerprint(market) == proposal.duplicate_fingerprint
            )
        if not compatible:
            raise ValidationError({"code": "market_proposal_duplicate_target_incompatible"})

    @classmethod
    @transaction.atomic
    def review(
        cls,
        *,
        proposal_id,
        actor,
        action,
        reason="",
        duplicate_of_market=None,
        duplicate_of_proposal=None,
    ):
        proposal = (
            MarketProposal.objects.select_for_update(of=("self",))
            .select_related("category", "sporting_event", "proposed_event_group")
            .get(id=proposal_id)
        )
        if (
            action == MarketProposalReview.Action.APPROVE
            and proposal.status == MarketProposal.Status.APPROVED
        ):
            return proposal
        if (
            action == MarketProposalReview.Action.APPROVE
            and proposal.duplicate_status == MarketProposal.DuplicateStatus.CONFIRMED_DUPLICATE
        ):
            raise MarketProposalDuplicateConflict()
        if proposal.status not in (
            MarketProposal.Status.SUBMITTED,
            MarketProposal.Status.UNDER_REVIEW,
        ):
            raise ValidationError({"code": "market_proposal_invalid_transition"})
        previous = proposal.status
        if action == MarketProposalReview.Action.START_REVIEW:
            if proposal.status == MarketProposal.Status.UNDER_REVIEW:
                return proposal
            new_status = MarketProposal.Status.UNDER_REVIEW
        elif action == MarketProposalReview.Action.REJECT:
            if not reason.strip():
                raise ValidationError({"code": "market_proposal_review_reason_required"})
            new_status = MarketProposal.Status.REJECTED
        elif action == MarketProposalReview.Action.MARK_DUPLICATE:
            if not reason.strip():
                raise ValidationError({"code": "market_proposal_review_reason_required"})
            cls._validate_duplicate_target(proposal, duplicate_of_market, duplicate_of_proposal)
            proposal.duplicate_of_market = duplicate_of_market
            proposal.duplicate_of_proposal = duplicate_of_proposal
            proposal.duplicate_status = MarketProposal.DuplicateStatus.CONFIRMED_DUPLICATE
            new_status = MarketProposal.Status.DUPLICATE
        elif action == MarketProposalReview.Action.APPROVE:
            group = cls._canonical_group(proposal, actor)
            # The sporting-event row is locked by _canonical_group. Recheck the
            # indexed market key inside that lock so duplicate proposals serialize.
            if cls.duplicate_candidates(proposal)["markets"]:
                raise MarketProposalDuplicateConflict()
            market = MarketCatalogService.create_market(
                sport=proposal.sporting_event.sport,
                category=proposal.category,
                scope_type=MarketScope.EVENT,
                sporting_event=proposal.sporting_event,
                event_group=group,
                question=proposal.question,
                description=proposal.description,
                resolution_source=proposal.proposed_resolution_source,
                closes_at=proposal.proposed_closes_at,
                status=Market.Status.DRAFT,
                created_by=actor,
            )
            proposal.approved_market = market
            new_status = MarketProposal.Status.APPROVED
        else:
            raise ValidationError({"code": "market_proposal_action_unsupported"})
        proposal.status = new_status
        proposal.reviewed_by = actor
        proposal.reviewed_at = timezone.now()
        proposal.save()
        MarketProposalReview.objects.create(
            proposal=proposal,
            actor=actor,
            action=action,
            previous_status=previous,
            new_status=new_status,
            reason=reason,
            duplicate_market=duplicate_of_market,
            duplicate_proposal=duplicate_of_proposal,
            approved_market=proposal.approved_market,
        )
        return proposal
