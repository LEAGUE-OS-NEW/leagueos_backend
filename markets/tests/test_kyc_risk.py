import hashlib
import hmac
import json
import time

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import override_settings

from markets.models import KYCVerificationEvent, MarketParticipantCompliance
from markets.services.kyc_service import (
    InvalidCallback,
    KYCError,
    KYCService,
    ManualKYCAdapter,
    get_adapter,
)
from markets.services.risk_service import MarketRiskService


@pytest.fixture
def participant(db):
    return get_user_model().objects.create_user(
        email="kyc@example.com", username="kyc", password="test"
    )


@pytest.mark.django_db(transaction=True)
@override_settings(MARKET_KYC_PROVIDER="manual", MARKET_KYC_WEBHOOK_SECRET="test-secret")
def test_kyc_idempotency_signed_callback_and_compliance(participant):
    session, created = KYCService.start(
        participant=participant, initiated_by=participant, idempotency_key="request-1"
    )
    replay, replay_created = KYCService.start(
        participant=participant, initiated_by=participant, idempotency_key="request-1"
    )
    assert created and not replay_created and replay.id == session.id
    payload = json.dumps(
        {
            "event_id": "provider-event-1",
            "external_reference": session.external_reference,
            "status": "VERIFIED",
        },
        separators=(",", ":"),
    ).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(
        b"test-secret", stamp.encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    updated, event, applied = KYCService.handle_callback(
        provider="manual", body=payload, timestamp=stamp, signature=signature
    )
    assert applied and updated.status == "VERIFIED"
    assert MarketParticipantCompliance.objects.get(participant=participant).kyc_status == "VERIFIED"
    _, duplicate, duplicate_applied = KYCService.handle_callback(
        provider="manual", body=payload, timestamp=stamp, signature=signature
    )
    assert not duplicate_applied and duplicate.id == event.id
    assert participant.market_compliance_reviews.filter(source="PROVIDER").count() == 1


@pytest.mark.django_db
@override_settings(MARKET_KYC_PROVIDER="manual", MARKET_KYC_WEBHOOK_SECRET="test-secret")
def test_callback_rejects_invalid_signature(participant):
    with pytest.raises(InvalidCallback):
        KYCService.handle_callback(
            provider="manual", body=b"{}", timestamp=str(int(time.time())), signature="bad"
        )


@pytest.mark.django_db
def test_kyc_event_is_immutable(participant):
    session, _ = KYCService.start(
        participant=participant, initiated_by=participant, idempotency_key="immutable"
    )
    event = session.events.first()
    event.event_type = "CHANGED"
    with pytest.raises(ValidationError):
        event.save()
    with pytest.raises(ValidationError):
        KYCVerificationEvent.objects.filter(pk=event.pk).delete()


@pytest.mark.django_db
def test_risk_rules_are_deterministic_and_idempotent(participant):
    MarketParticipantCompliance.objects.create(
        participant=participant, restriction_status="SUSPENDED"
    )
    profile, assessment, created = MarketRiskService.assess(participant=participant)
    again, repeated, repeated_created = MarketRiskService.assess(participant=participant)
    assert profile.current_score == 70 and profile.risk_band == "CRITICAL"
    assert profile.reason_codes == ["COMPLIANCE_SUSPENDED"]
    assert created and not repeated_created and assessment.id == repeated.id


@pytest.mark.django_db
def test_kyc_validation_terminal_and_active_branches(participant):
    adapter = ManualKYCAdapter()
    with pytest.raises(InvalidCallback):
        adapter.normalize_event({})
    with pytest.raises(InvalidCallback):
        adapter.normalize_event({"status": "UNKNOWN", "external_reference": "x"})
    with pytest.raises(KYCError):
        get_adapter("unsupported")
    session, _ = KYCService.start(
        participant=participant, idempotency_key="branches", initiated_by=participant
    )
    active, created = KYCService.start(
        participant=participant, idempotency_key="active", initiated_by=participant
    )
    assert active == session and not created
    KYCService.cancel(session=session, actor=participant)
    assert KYCService.cancel(session=session, actor=participant).status == "CANCELLED"
    assert not KYCService.verify_signature(body=b"{}", timestamp="bad", signature="x")
    with pytest.raises(InvalidCallback):
        KYCService.handle_callback(
            provider="manual", body=b"x" * 70000, timestamp="1", signature="x"
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kyc,restriction,jurisdiction,expected",
    [
        ("REJECTED", "RESTRICTED", "NONE", "CRITICAL"),
        ("EXPIRED", "CLEAR", "NONE", "MEDIUM"),
        ("VERIFIED", "CLEAR", "BLOCK", "CRITICAL"),
    ],
)
def test_risk_rule_branches(participant, kyc, restriction, jurisdiction, expected):
    MarketParticipantCompliance.objects.create(
        participant=participant,
        kyc_status=kyc,
        restriction_status=restriction,
        jurisdiction_override=jurisdiction,
    )
    profile, _, _ = MarketRiskService.assess(participant=participant)
    assert profile.risk_band == expected
