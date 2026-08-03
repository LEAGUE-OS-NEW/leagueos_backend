from datetime import date

from markets.models import MarketParticipantCompliance
from profiles.models import Country
from profiles.services.profile_service import ProfileService


def make_market_eligible(user, *, date_of_birth=None, country_code="UG"):
    country, _ = Country.objects.get_or_create(
        iso_code=country_code.upper(),
        defaults={"name": f"Test Country {country_code.upper()}"},
    )
    profile = ProfileService.get_or_create_profile(user)
    profile.date_of_birth = date_of_birth or date(1990, 1, 1)
    profile.country = country
    profile.save(update_fields=["date_of_birth", "country", "updated_at"])
    compliance, _ = MarketParticipantCompliance.objects.update_or_create(
        participant=user,
        defaults={
            "kyc_status": MarketParticipantCompliance.KYCStatus.VERIFIED,
            "restriction_status": MarketParticipantCompliance.RestrictionStatus.CLEAR,
            "jurisdiction_override": MarketParticipantCompliance.JurisdictionOverride.NONE,
        },
    )
    return compliance
