from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from markets.models import Market, MarketEventGroup


class MarketEventService:
    @classmethod
    def create(cls, *, actor, **data):
        group = MarketEventGroup(created_by=actor, status=MarketEventGroup.Status.DRAFT, **data)
        group.full_clean()
        group.save()
        return group

    @classmethod
    @transaction.atomic
    def update(cls, *, event_id, **data):
        group = get_object_or_404(MarketEventGroup.objects.select_for_update(), id=event_id)
        markets = list(
            Market.objects.select_for_update()
            .filter(event_group=group)
            .only("id", "sporting_event_id")
        )
        identity_fields = {"event_type", "sporting_event"}
        if group.status != MarketEventGroup.Status.DRAFT and identity_fields.intersection(data):
            changed = any(
                (
                    (
                        getattr(data[field], "id", data[field])
                        if data.get(field) is not None
                        else None
                    )
                    != getattr(group, f"{field}_id", None)
                    if field == "sporting_event"
                    else data[field] != getattr(group, field)
                )
                for field in identity_fields.intersection(data)
            )
            if changed:
                raise ValidationError({"code": "market_event_identity_frozen"})
        new_event = data.get("sporting_event", group.sporting_event)
        new_type = data.get("event_type", group.event_type)
        if markets:
            if new_type != MarketEventGroup.EventType.SPORTING_EVENT and any(
                market.sporting_event_id for market in markets
            ):
                raise ValidationError({"code": "market_event_context_conflict"})
            if any(
                market.sporting_event_id != getattr(new_event, "id", None)
                for market in markets
                if market.sporting_event_id
            ):
                raise ValidationError({"code": "market_event_context_conflict"})
        for field, value in data.items():
            setattr(group, field, value)
        group.full_clean()
        group.save()
        return group

    @classmethod
    @transaction.atomic
    def publish(cls, *, event_id, actor):
        group = get_object_or_404(MarketEventGroup.objects.select_for_update(), id=event_id)
        if group.status != MarketEventGroup.Status.DRAFT:
            raise ValidationError({"code": "market_event_invalid_transition"})
        if not group.title.strip():
            raise ValidationError({"title": "A title is required before publication."})
        group.status = MarketEventGroup.Status.PUBLISHED
        group.published_by = actor
        group.published_at = timezone.now()
        group.full_clean()
        group.save(update_fields=["status", "published_by", "published_at", "updated_at"])
        return group

    @classmethod
    @transaction.atomic
    def archive(cls, *, event_id, actor):
        group = get_object_or_404(MarketEventGroup.objects.select_for_update(), id=event_id)
        if group.status != MarketEventGroup.Status.PUBLISHED:
            raise ValidationError({"code": "market_event_invalid_transition"})
        group.status = MarketEventGroup.Status.ARCHIVED
        group.save(update_fields=["status", "updated_at"])
        return group

    @classmethod
    @transaction.atomic
    def attach_market(cls, *, event_id, market_id):
        group = get_object_or_404(MarketEventGroup.objects.select_for_update(), id=event_id)
        market = get_object_or_404(Market.objects.select_for_update(), id=market_id)
        if group.status == MarketEventGroup.Status.ARCHIVED:
            raise ValidationError({"code": "market_event_invalid_transition"})
        if market.event_group_id == group.id:
            return market
        if market.event_group_id:
            raise ValidationError({"code": "market_event_market_conflict"})
        if group.sporting_event_id and market.sporting_event_id != group.sporting_event_id:
            raise ValidationError({"code": "market_event_market_conflict"})
        if (
            group.event_type == MarketEventGroup.EventType.SPORTING_EVENT
            and not group.sporting_event_id
        ):
            raise ValidationError({"code": "market_event_market_conflict"})
        if (
            group.event_type != MarketEventGroup.EventType.SPORTING_EVENT
            and market.sporting_event_id
        ):
            raise ValidationError({"code": "market_event_market_conflict"})
        market.event_group = group
        market.full_clean()
        market.save(update_fields=["event_group", "duplicate_fingerprint", "updated_at"])
        return market

    @classmethod
    @transaction.atomic
    def detach_market(cls, *, event_id, market_id):
        group = get_object_or_404(MarketEventGroup.objects.select_for_update(), id=event_id)
        market = get_object_or_404(Market.objects.select_for_update(), id=market_id)
        if market.event_group_id == group.id:
            market.event_group = None
            market.save(update_fields=["event_group", "duplicate_fingerprint", "updated_at"])
        return market
