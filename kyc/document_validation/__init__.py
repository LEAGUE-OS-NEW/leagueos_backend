from kyc.document_validation.base import BaseDocumentValidator
from kyc.document_validation.driving_licence import DrivingLicenceValidator
from kyc.document_validation.national_id import NationalIDValidator
from kyc.document_validation.passport import PassportValidator

__all__ = [
    "BaseDocumentValidator",
    "PassportValidator",
    "NationalIDValidator",
    "DrivingLicenceValidator",
    "get_document_validator",
]


def get_document_validator(document_type: str, country_code: str = "UGA") -> BaseDocumentValidator:
    doc_type_upper = (document_type or "").upper()
    if doc_type_upper == "PASSPORT":
        return PassportValidator(country_code=country_code)
    elif doc_type_upper in ("NATIONAL_ID", "ID_CARD"):
        return NationalIDValidator(country_code=country_code)
    elif doc_type_upper in ("DRIVING_LICENCE", "DRIVER_LICENSE"):
        return DrivingLicenceValidator(country_code=country_code)
    else:
        return BaseDocumentValidator(country_code=country_code)
