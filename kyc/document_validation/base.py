from abc import ABC, abstractmethod
from typing import Any


class BaseDocumentValidator(ABC):
    """Abstract base class for document format, structure, and field validators."""

    def __init__(self, country_code: str = "UGA"):
        self.country_code = country_code.upper()

    @abstractmethod
    def validate_structure(self, image_metadata: dict[str, Any], raw_text: str) -> dict[str, Any]:
        """Validates document aspect ratio, structural layout, and presence of mandatory markers."""
        pass

    @abstractmethod
    def parse_fields(self, raw_text: str) -> dict[str, Any]:
        """Parses extracted OCR text into normalized identity fields."""
        pass

    def validate_expiry(self, expiry_date_str: str | None) -> dict[str, Any]:
        """Validates document expiry date against server date."""
        if not expiry_date_str:
            return {"status": "UNCERTAIN", "is_expired": None, "reason": "No expiry date found"}

        from django.utils import timezone
        import datetime

        try:
            # Attempt common date format parsing
            exp_date = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d", "%d %b %Y"):
                try:
                    exp_date = datetime.datetime.strptime(expiry_date_str.strip(), fmt).date()
                    break
                except ValueError:
                    continue

            if not exp_date:
                return {
                    "status": "UNCERTAIN",
                    "is_expired": None,
                    "reason": "Unrecognized date format",
                }

            today = timezone.now().date()
            is_expired = exp_date < today
            return {
                "status": "FAILED" if is_expired else "PASSED",
                "is_expired": is_expired,
                "expiry_date": exp_date.isoformat(),
            }
        except Exception as e:
            return {"status": "UNCERTAIN", "is_expired": None, "reason": str(e)}
