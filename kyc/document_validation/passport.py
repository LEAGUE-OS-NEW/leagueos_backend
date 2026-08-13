import re
from datetime import date
from typing import Any
from kyc.document_validation.base import BaseDocumentValidator


class PassportValidator(BaseDocumentValidator):
    """Passport document validator and TD3 MRZ parser."""

    @staticmethod
    def _mrz_char_value(char: str) -> int:
        if char == "<":
            return 0
        if char.isdigit():
            return int(char)
        if char.isalpha():
            return ord(char.upper()) - 55
        return 0

    @classmethod
    def calculate_mrz_checksum(cls, data: str) -> int:
        weights = [7, 3, 1]
        total = 0
        for i, char in enumerate(data):
            total += cls._mrz_char_value(char) * weights[i % 3]
        return total % 10

    def parse_mrz(self, text: str) -> dict[str, Any]:
        """Parses ICAO Doc 9303 TD3 2-line MRZ string (44 characters per line)."""
        lines = [
            line.strip().replace(" ", "")
            for line in text.splitlines()
            if len(line.strip().replace(" ", "")) >= 40
        ]

        # Look for 2 consecutive lines with length 44
        mrz_line1, mrz_line2 = None, None
        for i in range(len(lines) - 1):
            l1, l2 = lines[i], lines[i + 1]
            if len(l1) == 44 and len(l2) == 44 and l1.startswith("P"):
                mrz_line1, mrz_line2 = l1, l2
                break

        if not mrz_line1 or not mrz_line2:
            return {
                "status": "NOT_APPLICABLE",
                "valid": False,
                "reason": "No valid 2-line 44-character MRZ found",
            }

        try:
            # Line 1 parsing: P<COUNTRYNAME<<FIRSTNAME<SECONDNAME...
            doc_type = mrz_line1[0:2]
            country = mrz_line1[2:5]
            names = mrz_line1[5:44].split("<<")
            surname = names[0].replace("<", " ").strip() if len(names) > 0 else ""
            given_names = names[1].replace("<", " ").strip() if len(names) > 1 else ""
            full_name = f"{given_names} {surname}".strip()

            # Line 2 parsing: DOCNUM(9) + CHK(1) + NAT(3) + DOB(6) + CHK(1) +
            # SEX(1) + EXP(6) + CHK(1) + OPT(14) + CHK(1)
            doc_number = mrz_line2[0:9].replace("<", "")
            doc_number_chk = mrz_line2[9]
            nationality = mrz_line2[10:13]
            dob_str = mrz_line2[13:19]
            dob_chk = mrz_line2[19]
            sex = mrz_line2[20]
            expiry_str = mrz_line2[21:27]
            expiry_chk = mrz_line2[27]

            # Validate check digits
            doc_num_valid = (
                self.calculate_mrz_checksum(mrz_line2[0:9]) == int(doc_number_chk)
                if doc_number_chk.isdigit()
                else False
            )
            dob_valid = (
                self.calculate_mrz_checksum(dob_str) == int(dob_chk) if dob_chk.isdigit() else False
            )
            expiry_valid = (
                self.calculate_mrz_checksum(expiry_str) == int(expiry_chk)
                if expiry_chk.isdigit()
                else False
            )

            all_valid = doc_num_valid and dob_valid and expiry_valid

            # Parse DOB YYMMDD -> YYYY-MM-DD
            yy = int(dob_str[:2])
            current_yy = date.today().year % 100
            century_pivot = (current_yy + 30) % 100
            dob_yyyy = (
                f"20{yy:02d}-{dob_str[2:4]}-{dob_str[4:6]}"
                if yy <= century_pivot
                else f"19{yy:02d}-{dob_str[2:4]}-{dob_str[4:6]}"
            )

            # Parse Expiry YYMMDD -> YYYY-MM-DD
            exp_yy = int(expiry_str[:2])
            exp_yyyy = (
                f"20{exp_yy:02d}-{expiry_str[2:4]}-{expiry_str[4:6]}"
                if exp_yy <= century_pivot
                else f"19{exp_yy:02d}-{expiry_str[2:4]}-{expiry_str[4:6]}"
            )

            return {
                "status": "PASSED" if all_valid else "FAILED",
                "valid": all_valid,
                "document_type": doc_type,
                "country": country,
                "nationality": nationality,
                "full_name": full_name,
                "document_number": doc_number,
                "date_of_birth": dob_yyyy,
                "expiry_date": exp_yyyy,
                "gender": sex,
                "check_digits": {
                    "doc_number_valid": doc_num_valid,
                    "dob_valid": dob_valid,
                    "expiry_valid": expiry_valid,
                },
            }
        except Exception as e:
            return {"status": "FAILED", "valid": False, "reason": f"MRZ parsing error: {e}"}

    def validate_structure(self, image_metadata: dict[str, Any], raw_text: str) -> dict[str, Any]:
        width, height = image_metadata.get("width", 0), image_metadata.get("height", 0)
        aspect_ratio = width / height if height > 0 else 0.0

        # Passport aspect ratio expectation (~1.3 to 1.6)
        aspect_valid = 1.1 <= aspect_ratio <= 1.8
        has_passport_keyword = any(
            kw in raw_text.lower() for kw in ["passport", "passeport", "pasaporte", "republic"]
        )

        return {
            "status": "PASSED" if (aspect_valid or has_passport_keyword) else "UNCERTAIN",
            "aspect_ratio": round(aspect_ratio, 2),
            "aspect_valid": aspect_valid,
            "has_passport_keyword": has_passport_keyword,
        }

    def parse_fields(self, raw_text: str) -> dict[str, Any]:
        mrz_result = self.parse_mrz(raw_text)
        if mrz_result.get("valid"):
            return {
                "full_name": mrz_result.get("full_name"),
                "document_number": mrz_result.get("document_number"),
                "date_of_birth": mrz_result.get("date_of_birth"),
                "expiry_date": mrz_result.get("expiry_date"),
                "nationality": mrz_result.get("nationality"),
                "mrz_result": mrz_result,
            }

        # Regex fallback for text OCR
        doc_num_match = re.search(r"\b[A-Z0-9]{8,10}\b", raw_text)
        date_match = re.search(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b", raw_text)

        return {
            "full_name": None,
            "document_number": doc_num_match.group(0) if doc_num_match else None,
            "date_of_birth": None,
            "expiry_date": date_match.group(0) if date_match else None,
            "nationality": self.country_code,
            "mrz_result": mrz_result,
        }
