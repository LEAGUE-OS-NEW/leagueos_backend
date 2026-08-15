from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.utils import timezone

from kyc.models import KYCVerification
from markets.models import MarketParticipantCompliance, MarketRiskProfile
from profiles.models import Profile

_UNSET = object()


@dataclass(frozen=True)
class MarketEligibilityResult:
    eligible: bool
    evaluated_at: object
    minimum_age: int
    age: int | None
    age_eligible: bool
    date_of_birth_present: bool
    country_code: str | None
    jurisdiction_eligible: bool
    kyc_status: str
    kyc_eligible: bool
    restriction_status: str
    restriction_clear: bool
    jurisdiction_override: str
    reason_codes: tuple[str, ...]
    next_actions: tuple[str, ...]

    def as_dict(self):
        return {
            "eligible": self.eligible,
            "evaluated_at": self.evaluated_at,
            "requirements": {
                "minimum_age": self.minimum_age,
                "age": self.age,
                "age_eligible": self.age_eligible,
                "date_of_birth_present": self.date_of_birth_present,
                "country_code": self.country_code,
                "jurisdiction_eligible": self.jurisdiction_eligible,
                "kyc_status": self.kyc_status,
                "kyc_eligible": self.kyc_eligible,
                "restriction_status": self.restriction_status,
                "restriction_clear": self.restriction_clear,
                "jurisdiction_override": self.jurisdiction_override,
            },
            "reason_codes": self.reason_codes,
            "next_actions": self.next_actions,
        }


class MarketEligibilityService:
    @staticmethod
    def _configured_country_codes(setting_name):
        return {
            normalized
            for code in getattr(settings, setting_name, [])
            if (normalized := str(code).strip().upper())
        }

    @staticmethod
    def evaluate(
        *,
        participant,
        as_of_date: date | None = None,
        profile=_UNSET,
        compliance=_UNSET,
    ):
        evaluated_at = timezone.now()
        today = as_of_date or timezone.localdate(evaluated_at)
        minimum_age = int(getattr(settings, "MARKET_MINIMUM_AGE", 18))
        if profile is _UNSET:
            try:
                profile = participant.profile
            except Profile.DoesNotExist:
                profile = None
        dob = profile.date_of_birth if profile else None
        age = None
        if dob:
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        age_eligible = age is not None and age >= minimum_age
        country_code = None
        if profile and profile.country_id:
            country_code = profile.country.iso_code.upper()
        country_valid = bool(country_code and len(country_code) == 2 and country_code.isalpha())
        if compliance is _UNSET:
            compliance = (
                MarketParticipantCompliance.objects.filter(participant=participant)
                .select_related("participant__market_risk_profile")
                .first()
            )
        kyc_verification = KYCVerification.objects.filter(user=participant).first()
        if kyc_verification:
            kyc = kyc_verification.status
            kyc_eligible = kyc == KYCVerification.Status.VERIFIED
        else:
            kyc = KYCVerification.Status.NOT_STARTED
            kyc_eligible = False
        restriction = (
            compliance.restriction_status
            if compliance
            else MarketParticipantCompliance.RestrictionStatus.CLEAR
        )
        restriction_clear = restriction == MarketParticipantCompliance.RestrictionStatus.CLEAR
        override = (
            compliance.jurisdiction_override
            if compliance
            else MarketParticipantCompliance.JurisdictionOverride.NONE
        )
        allowed = MarketEligibilityService._configured_country_codes("MARKET_ALLOWED_COUNTRY_CODES")
        blocked = MarketEligibilityService._configured_country_codes("MARKET_BLOCKED_COUNTRY_CODES")
        jurisdiction_eligible = country_valid
        if country_valid:
            jurisdiction_eligible = country_code not in blocked and (
                not allowed or country_code in allowed
            )
        if override == MarketParticipantCompliance.JurisdictionOverride.ALLOW and country_valid:
            jurisdiction_eligible = True
        elif override == MarketParticipantCompliance.JurisdictionOverride.BLOCK:
            jurisdiction_eligible = False

        reasons = []
        if not dob:
            reasons.append("DATE_OF_BIRTH_REQUIRED")
        elif not age_eligible:
            reasons.append("AGE_RESTRICTED")
        if not country_code:
            reasons.append("COUNTRY_REQUIRED")
        elif not country_valid:
            reasons.append("COUNTRY_INVALID")
        elif not jurisdiction_eligible:
            reasons.append("JURISDICTION_BLOCKED")
        if not kyc_eligible:
            reasons.append(f"KYC_{kyc}")
        if not restriction_clear:
            reasons.append(f"COMPLIANCE_{restriction}")
        risk_band = MarketRiskProfile.Band.LOW
        override_state = "NONE"
        if compliance:
            try:
                risk_profile = compliance.participant.market_risk_profile
                risk_band = risk_profile.risk_band
                override_state = risk_profile.manual_override_state
            except MarketRiskProfile.DoesNotExist:
                pass
        if override_state == "BLOCK":
            reasons.append("RISK_CRITICAL")
        elif override_state == "REVIEW":
            reasons.append("RISK_REVIEW_REQUIRED")
        elif override_state == "CLEAR":
            pass
        elif risk_band == MarketRiskProfile.Band.CRITICAL:
            reasons.append("RISK_CRITICAL")
        elif risk_band == MarketRiskProfile.Band.HIGH:
            reasons.append("RISK_REVIEW_REQUIRED")
        actions = []
        if any(
            code in reasons
            for code in ("DATE_OF_BIRTH_REQUIRED", "COUNTRY_REQUIRED", "COUNTRY_INVALID")
        ):
            actions.append("COMPLETE_PROFILE")
        if "KYC_NOT_STARTED" in reasons:
            actions.append("COMPLETE_KYC")
        if "KYC_PENDING" in reasons:
            actions.append("WAIT_FOR_KYC_REVIEW")
        if any(
            code in reasons
            for code in (
                "AGE_RESTRICTED",
                "JURISDICTION_BLOCKED",
                "KYC_REJECTED",
                "KYC_EXPIRED",
                "COMPLIANCE_RESTRICTED",
                "COMPLIANCE_SUSPENDED",
                "RISK_CRITICAL",
                "RISK_REVIEW_REQUIRED",
            )
        ):
            actions.append("CONTACT_SUPPORT")
        return MarketEligibilityResult(
            not reasons,
            evaluated_at,
            minimum_age,
            age,
            age_eligible,
            bool(dob),
            country_code,
            jurisdiction_eligible,
            kyc,
            kyc_eligible,
            restriction,
            restriction_clear,
            override,
            tuple(reasons),
            tuple(actions),
        )
