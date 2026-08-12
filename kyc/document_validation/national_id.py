import re
from typing import Any
from kyc.document_validation.base import BaseDocumentValidator


class NationalIDValidator(BaseDocumentValidator):
    """Extensible National ID document validator with country format specifications."""

    COUNTRY_PATTERNS = {
        "UGA": {
            "doc_number_regex": r"\bCM\d{13}\b|\bCF\d{13}\b|\b[A-Z]{2}\d{13}\b",
            "keywords": ["republic of uganda", "national identity card", "national id", "nin"],
        },
        "KEN": {
            "doc_number_regex": r"\b\d{8}\b",
            "keywords": ["republic of kenya", "national identity card", "id number"],
        },
        "USA": {
            "doc_number_regex": r"\b\d{3}-\d{2}-\d{4}\b|\b[A-Z0-9]{8,11}\b",
            "keywords": ["state", "identification card", "id card"],
        },
        "GBR": {
            "doc_number_regex": r"\b[A-Z]{2}\d{6}[A-Z]\b",
            "keywords": ["united kingdom", "national identity"],
        },
    }

    def validate_structure(self, image_metadata: dict[str, Any], raw_text: str) -> dict[str, Any]:
        width, height = image_metadata.get("width", 0), image_metadata.get("height", 0)
        aspect_ratio = width / height if height > 0 else 0.0

        # ID Cards usually have ID-1 format aspect ratio (~1.4 to 1.7)
        aspect_valid = 1.2 <= aspect_ratio <= 1.8
        pattern_info = self.COUNTRY_PATTERNS.get(self.country_code, {})
        keywords = pattern_info.get("keywords", ["identity", "id card", "national"])

        has_keyword = any(kw in raw_text.lower() for kw in keywords)

        return {
            "status": "PASSED" if (aspect_valid or has_keyword) else "UNCERTAIN",
            "aspect_ratio": round(aspect_ratio, 2),
            "aspect_valid": aspect_valid,
            "has_keyword": has_keyword,
        }

    def parse_fields(self, raw_text: str) -> dict[str, Any]:
        pattern_info = self.COUNTRY_PATTERNS.get(self.country_code, {})
        doc_regex = pattern_info.get("doc_number_regex", r"\b[A-Z0-9]{8,14}\b")

        doc_num_match = re.search(doc_regex, raw_text)
        dob_match = re.search(
            r"(?:dob|birth|date of birth)[:\s]*(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}[/-]\d{2}[/-]\d{2})",
            raw_text,
            re.I,
        )
        exp_match = re.search(
            r"(?:exp|expiry|expiry date)[:\s]*(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}[/-]\d{2}[/-]\d{2})",
            raw_text,
            re.I,
        )
        name_match = re.search(r"(?:name|surname|given names)[:\s]*([A-Z\s]{3,40})", raw_text, re.I)

        return {
            "full_name": name_match.group(1).strip() if name_match else None,
            "document_number": doc_num_match.group(0) if doc_num_match else None,
            "date_of_birth": dob_match.group(1) if dob_match else None,
            "expiry_date": exp_match.group(1) if exp_match else None,
            "nationality": self.country_code,
        }
