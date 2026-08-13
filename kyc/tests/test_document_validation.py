from kyc.document_validation.passport import PassportValidator
from kyc.document_validation.national_id import NationalIDValidator
from kyc.document_validation.driving_licence import DrivingLicenceValidator


def test_passport_mrz_valid_parsing():
    validator = PassportValidator()
    # Construct valid 2-line TD3 MRZ sample
    # Line 1: P<UGAAKIROR<<FAITH<<<<<<<<<<<<<<<<<<<<<<<<<
    # Line 2: A123456787UGA9001014M3001015<<<<<<<<<<<<<<02
    line1 = "P<UGAAKIROR<<FAITH" + "<" * 26
    # Calculate valid check digits for line 2
    # doc num A12345678 -> checksum
    doc_num = "A12345678"
    doc_chk = validator.calculate_mrz_checksum(doc_num)
    dob = "900101"
    dob_chk = validator.calculate_mrz_checksum(dob)
    exp = "300101"
    exp_chk = validator.calculate_mrz_checksum(exp)

    line2 = f"{doc_num}{doc_chk}UGA{dob}{dob_chk}M{exp}{exp_chk}" + "<" * 14 + "0" + "0"
    mrz_text = f"{line1}\n{line2}"

    res = validator.parse_mrz(mrz_text)

    assert res["status"] == "PASSED"
    assert res["valid"] is True
    assert res["full_name"] == "FAITH AKIROR"
    assert res["document_number"] == "A12345678"
    assert res["date_of_birth"] == "1990-01-01"
    assert res["expiry_date"] == "2030-01-01"


def test_national_id_validator():
    validator = NationalIDValidator(country_code="UGA")
    text = "REPUBLIC OF UGANDA\nNATIONAL IDENTITY CARD\nNIN: CM9001011234567\nNAME: FAITH AKIROR"
    parsed = validator.parse_fields(text)

    assert parsed["document_number"] == "CM9001011234567"
    assert parsed["full_name"] == "FAITH AKIROR"


def test_driving_licence_validator():
    validator = DrivingLicenceValidator(country_code="UGA")
    text = "DRIVING LICENCE\n1 AKIROR FAITH\nDL12345678\n4b 2030-05-10"
    parsed = validator.parse_fields(text)

    assert parsed["document_number"] == "DL12345678"
    assert parsed["full_name"] == "AKIROR FAITH"
