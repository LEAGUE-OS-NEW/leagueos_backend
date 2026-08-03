from datetime import date

from django.test import TestCase, override_settings

from authentication.tests.factories import UserFactory
from markets.models import MarketParticipantCompliance
from markets.services.eligibility_service import MarketEligibilityService
from markets.tests.eligibility_test_support import make_market_eligible


class MarketEligibilityServiceTests(TestCase):
    def test_missing_identity_and_compliance_fail_closed(self):
        participant = UserFactory()

        result = MarketEligibilityService.evaluate(
            participant=participant,
            as_of_date=date(2026, 8, 3),
        )

        self.assertFalse(result.eligible)
        self.assertEqual(
            result.reason_codes,
            (
                "DATE_OF_BIRTH_REQUIRED",
                "COUNTRY_REQUIRED",
                "KYC_NOT_STARTED",
            ),
        )
        self.assertEqual(result.next_actions, ("COMPLETE_PROFILE", "COMPLETE_KYC"))

    def evaluate(self, participant, day=date(2026, 8, 3)):
        return MarketEligibilityService.evaluate(participant=participant, as_of_date=day)

    def test_age_calendar_boundaries_and_leap_day(self):
        participant = UserFactory()
        make_market_eligible(participant, date_of_birth=date(2008, 8, 3))
        self.assertTrue(self.evaluate(participant).age_eligible)
        participant.profile.date_of_birth = date(2008, 8, 4)
        participant.profile.save()
        self.assertFalse(self.evaluate(participant).age_eligible)
        participant.profile.date_of_birth = date(2008, 2, 29)
        participant.profile.save()
        self.assertEqual(self.evaluate(participant, date(2026, 2, 28)).age, 17)
        self.assertEqual(self.evaluate(participant, date(2026, 3, 1)).age, 18)

    @override_settings(MARKET_MINIMUM_AGE=21)
    def test_configured_minimum_age(self):
        participant = UserFactory()
        make_market_eligible(participant, date_of_birth=date(2006, 8, 3))
        result = self.evaluate(participant)
        self.assertEqual(result.minimum_age, 21)
        self.assertIn("AGE_RESTRICTED", result.reason_codes)

    @override_settings(MARKET_BLOCKED_COUNTRY_CODES=["ug"])
    def test_blocked_country_and_allow_override(self):
        participant = UserFactory()
        compliance = make_market_eligible(participant, country_code="ug")
        self.assertIn("JURISDICTION_BLOCKED", self.evaluate(participant).reason_codes)
        compliance.jurisdiction_override = MarketParticipantCompliance.JurisdictionOverride.ALLOW
        compliance.save()
        result = self.evaluate(participant)
        self.assertTrue(result.jurisdiction_eligible)
        self.assertEqual(result.country_code, "UG")

    @override_settings(MARKET_ALLOWED_COUNTRY_CODES=["KE"])
    def test_allow_list_and_manual_block(self):
        participant = UserFactory()
        compliance = make_market_eligible(participant, country_code="UG")
        self.assertFalse(self.evaluate(participant).jurisdiction_eligible)
        compliance.jurisdiction_override = MarketParticipantCompliance.JurisdictionOverride.BLOCK
        compliance.save()
        participant.profile.country.iso_code = "KE"
        participant.profile.country.save()
        self.assertFalse(self.evaluate(participant).jurisdiction_eligible)

    def test_all_kyc_and_restriction_failures_have_stable_codes(self):
        participant = UserFactory()
        compliance = make_market_eligible(participant)
        for status in ("NOT_STARTED", "PENDING", "REJECTED", "EXPIRED"):
            compliance.kyc_status = status
            compliance.restriction_status = "CLEAR"
            compliance.save()
            self.assertIn(f"KYC_{status}", self.evaluate(participant).reason_codes)
        compliance.kyc_status = "VERIFIED"
        for status in ("RESTRICTED", "SUSPENDED"):
            compliance.restriction_status = status
            compliance.save()
            self.assertIn(f"COMPLIANCE_{status}", self.evaluate(participant).reason_codes)

    @override_settings(
        MARKET_ALLOWED_COUNTRY_CODES=[" ug ", "UG", " ke "],
        MARKET_BLOCKED_COUNTRY_CODES=[" tz ", "TZ"],
    )
    def test_country_configuration_is_trimmed_uppercased_and_deduplicated(self):
        self.assertEqual(
            MarketEligibilityService._configured_country_codes("MARKET_ALLOWED_COUNTRY_CODES"),
            {"UG", "KE"},
        )
        self.assertEqual(
            MarketEligibilityService._configured_country_codes("MARKET_BLOCKED_COUNTRY_CODES"),
            {"TZ"},
        )

    @override_settings(MARKET_ALLOWED_COUNTRY_CODES=[], MARKET_BLOCKED_COUNTRY_CODES=[])
    def test_empty_country_lists_allow_any_valid_country(self):
        participant = UserFactory()
        make_market_eligible(participant, country_code="ke")
        self.assertTrue(self.evaluate(participant).jurisdiction_eligible)
