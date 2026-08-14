import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from markets.models import KYCVerificationEvent, KYCVerificationSession
from markets.services.compliance_service import MarketComplianceService


class KYCError(Exception):
    pass


class InvalidCallback(KYCError):
    pass


@dataclass(frozen=True)
class NormalizedKYCEvent:
    event_id: str | None
    external_reference: str
    status: str
    provider_status: str
    occurred_at: object
    event_type: str
    metadata: dict


class ManualKYCAdapter:
    code = "manual"

    def create_session(self, session):
        return {
            "external_reference": f"local-{session.id}",
            "status": "PENDING",
            "continuation_url": "",
        }

    def normalize_event(self, payload):
        try:
            status = str(payload["status"]).upper()
            reference = str(payload["external_reference"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidCallback("Invalid callback data.") from exc
        if status not in KYCVerificationSession.Status.values:
            raise InvalidCallback("Unsupported provider status.")
        occurred = timezone.now()
        return NormalizedKYCEvent(
            str(payload.get("event_id")) if payload.get("event_id") else None,
            reference,
            status,
            str(payload.get("provider_status", status))[:100],
            occurred,
            str(payload.get("event_type", "STATUS_CHANGED"))[:64],
            {"reason_code": str(payload.get("reason_code", ""))[:100]},
        )


def get_adapter(provider):
    configured = str(getattr(settings, "MARKET_KYC_PROVIDER", "manual")).lower()
    if provider.lower() != configured or configured != "manual":
        raise KYCError("Unsupported KYC provider.")
    return ManualKYCAdapter()


class KYCService:
    TERMINAL = {"VERIFIED", "REJECTED", "EXPIRED", "CANCELLED", "ERROR"}

    @classmethod
    @transaction.atomic
    def start(
        cls, *, participant, idempotency_key, verification_level="STANDARD", initiated_by=None
    ):
        existing = (
            KYCVerificationSession.objects.select_for_update()
            .filter(participant=participant, client_idempotency_key=idempotency_key)
            .first()
        )
        if existing:
            return existing, False
        active = (
            KYCVerificationSession.objects.select_for_update()
            .filter(participant=participant)
            .exclude(status__in=cls.TERMINAL)
            .first()
        )
        if active:
            return active, False
        provider = getattr(settings, "MARKET_KYC_PROVIDER", "manual")
        adapter = get_adapter(provider)
        session = KYCVerificationSession.objects.create(
            participant=participant,
            provider_code=provider,
            client_idempotency_key=idempotency_key,
            verification_level=verification_level,
            initiated_by=initiated_by,
            expires_at=timezone.now()
            + timedelta(hours=int(getattr(settings, "MARKET_KYC_SESSION_HOURS", 24))),
        )
        result = adapter.create_session(session)
        session.external_reference = result["external_reference"]
        session.status = result["status"]
        session.continuation_url = result.get("continuation_url", "")
        session.save()
        KYCVerificationEvent.objects.create(
            session=session,
            event_type="SESSION_STARTED",
            previous_status="",
            new_status=session.status,
            provider_status=session.status,
            payload_digest=hashlib.sha256(f"start:{session.id}".encode()).hexdigest(),
            source=KYCVerificationEvent.Source.PARTICIPANT,
            actor=initiated_by,
        )
        MarketComplianceService.update(
            participant=participant, actor=None, source="SYSTEM", changes={"kyc_status": "PENDING"}
        )
        cls._notify(session, "KYC_STARTED")
        return session, True

    @classmethod
    @transaction.atomic
    def cancel(cls, *, session, actor):
        session = KYCVerificationSession.objects.select_for_update().get(pk=session.pk)
        if session.is_terminal:
            return session
        previous = session.status
        session.status = session.Status.CANCELLED
        session.completed_at = timezone.now()
        session.save()
        KYCVerificationEvent.objects.create(
            session=session,
            event_type="CANCELLED",
            previous_status=previous,
            new_status=session.status,
            payload_digest=hashlib.sha256(f"cancel:{session.id}".encode()).hexdigest(),
            source=KYCVerificationEvent.Source.PARTICIPANT,
            actor=actor,
        )
        return session

    @classmethod
    @transaction.atomic
    def admin_decide(cls, *, participant, decision, actor, notes=""):
        """Transitions the participant's current non-terminal KYC session
        (if any) to reflect a compliance admin's manual decision, mirroring
        the event-logging pattern _apply_event uses for provider webhooks.

        This keeps KYCVerificationSession (what the admin queue list reads)
        in sync with MarketParticipantCompliance.kyc_status (what actually
        gates eligibility), which a manual compliance decision otherwise
        only ever updates directly.
        """
        session = (
            KYCVerificationSession.objects.select_for_update()
            .filter(participant=participant)
            .exclude(status__in=cls.TERMINAL)
            .order_by("-initiated_at")
            .first()
        )
        if session is None:
            return None
        previous = session.status
        session.status = decision
        session.completed_at = timezone.now()
        session.save()
        KYCVerificationEvent.objects.create(
            session=session,
            event_type=f"ADMIN_{decision}",
            previous_status=previous,
            new_status=decision,
            payload_digest=hashlib.sha256(
                f"admin:{session.id}:{decision}:{timezone.now().timestamp()}".encode()
            ).hexdigest(),
            source=KYCVerificationEvent.Source.ADMIN,
            actor=actor,
            metadata={"notes": notes} if notes else {},
        )
        return session

    @classmethod
    def verify_signature(cls, *, body, timestamp, signature):
        secret = getattr(settings, "MARKET_KYC_WEBHOOK_SECRET", "")
        if not secret:
            return False
        try:
            stamp = int(timestamp)
        except (TypeError, ValueError):
            return False
        if abs(int(timezone.now().timestamp()) - stamp) > int(
            getattr(settings, "MARKET_KYC_WEBHOOK_TOLERANCE_SECONDS", 300)
        ):
            return False
        expected = hmac.new(
            secret.encode(), str(stamp).encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, str(signature))

    @classmethod
    def handle_callback(cls, *, provider, body, timestamp, signature):
        if len(body) > int(getattr(settings, "MARKET_KYC_MAX_CALLBACK_BYTES", 65536)):
            raise InvalidCallback("Callback payload is too large.")
        adapter = get_adapter(provider)
        if not cls.verify_signature(body=body, timestamp=timestamp, signature=signature):
            raise InvalidCallback("Invalid callback signature.")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidCallback("Malformed JSON callback.") from exc
        if not isinstance(payload, dict):
            raise InvalidCallback("Callback must be a JSON object.")
        event = adapter.normalize_event(payload)
        digest = hashlib.sha256(body).hexdigest()
        return cls._apply_event(provider, event, digest)

    @classmethod
    @transaction.atomic
    def _apply_event(cls, provider, event, digest):
        session = KYCVerificationSession.objects.select_for_update().get(
            provider_code=provider, external_reference=event.external_reference
        )
        duplicate = (
            KYCVerificationEvent.objects.filter(session=session)
            .filter(
                models.Q(external_event_id=event.event_id)
                if event.event_id
                else models.Q(payload_digest=digest)
            )
            .first()
        )
        if duplicate:
            return session, duplicate, False
        previous = session.status
        if session.is_terminal and event.status != previous:
            raise InvalidCallback("Terminal verification status cannot change.")
        session.status = event.status
        session.provider_status = event.provider_status
        session.last_event_at = event.occurred_at
        session.failure_code = event.metadata.get("reason_code", "")
        if session.is_terminal:
            session.completed_at = event.occurred_at
        session.save()
        audit = KYCVerificationEvent.objects.create(
            session=session,
            event_type=event.event_type,
            previous_status=previous,
            new_status=event.status,
            provider_status=event.provider_status,
            external_event_id=event.event_id,
            payload_digest=digest,
            metadata=event.metadata,
            source=KYCVerificationEvent.Source.PROVIDER,
            occurred_at=event.occurred_at,
        )
        mapping = {
            "VERIFIED": "VERIFIED",
            "REJECTED": "REJECTED",
            "EXPIRED": "EXPIRED",
            "PENDING": "PENDING",
            "IN_REVIEW": "PENDING",
        }
        if event.status in mapping:
            MarketComplianceService.update(
                participant=session.participant,
                actor=None,
                source="PROVIDER",
                changes={"kyc_status": mapping[event.status]},
                reason=f"KYC event {audit.id}",
            )
        if event.status == "IN_REVIEW":
            from notifications.services.operational_alert_service import OperationalAlertService

            OperationalAlertService.create(
                permissions=("manage_compliance",),
                event_type="KYC_MANUAL_REVIEW_REQUIRED",
                title="KYC manual review required",
                message="A KYC verification requires manual compliance review.",
                source_key=f"kyc-event:{audit.id}:manual-review",
                data={
                    "kyc_event_id": str(audit.id),
                    "session_id": str(session.id),
                    "provider_code": session.provider_code,
                },
            )
        cls._notify(session, f"KYC_{event.status}", event_id=audit.id)
        return session, audit, True

    @staticmethod
    def _notify(session, event_type, event_id=None):
        def create():
            try:
                from notifications.services.notification_service import NotificationService

                NotificationService.create(
                    recipient=session.participant,
                    category_code="MARKET_COMPLIANCE",
                    event_type=event_type,
                    title="Verification update",
                    message=session.status_message or event_type.replace("_", " ").title(),
                    deduplication_key=(
                        f"market-kyc-event:{event_id or session.id}:{event_type.lower()}"
                    ),
                    mandatory=True,
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception("Unable to create KYC notification")

        transaction.on_commit(create)


from django.db import models  # noqa: E402
