import re
from typing import Any
from kyc.document_validation.base import BaseDocumentValidator


class DrivingLicenceValidator(BaseDocumentValidator):
    """Driving Licence document validator."""

    KEYWORDS = ["driver", "driving", "licence", "license", "permis de conduire", "dl"]

    def validate_structure(self, image_metadata: dict[str, Any], raw_text: str) -> dict[str, Any]:
        width, height = image_metadata.get("width", 0), image_metadata.get("height", 0)
        aspect_ratio = width / height if height > 0 else 0.0

        aspect_valid = 1.2 <= aspect_ratio <= 1.8
        has_keyword = any(kw in raw_text.lower() for kw in self.KEYWORDS)

        return {
            "status": "PASSED" if (aspect_valid or has_keyword) else "UNCERTAIN",
            "aspect_ratio": round(aspect_ratio, 2),
            "aspect_valid": aspect_valid,
            "has_keyword": has_keyword,
        }

    def parse_fields(self, raw_text: str) -> dict[str, Any]:
        doc_num_match = re.search(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{7,15}\b", raw_text)
        dob_match = re.search(
            r"(?:dob|birth)[:\s]*(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}[/-]\d{2}[/-]\d{2})", raw_text, re.I
        )
        exp_match = re.search(
            r"(?:exp|4b|expires)[:\s]*(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}[/-]\d{2}[/-]\d{2})",
            raw_text,
            re.I,
        )
        name_match = re.search(r"(?:1|name)[:\s]*([^\n]{3,40})", raw_text, re.I)

        return {
            "full_name": name_match.group(1).strip() if name_match else None,
            "document_number": doc_num_match.group(0) if doc_num_match else None,
            "date_of_birth": dob_match.group(1) if dob_match else None,
            "expiry_date": exp_match.group(1) if exp_match else None,
            "nationality": self.country_code,
        }
