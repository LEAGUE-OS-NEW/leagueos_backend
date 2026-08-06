from collections import defaultdict
from dataclasses import dataclass, field

import phonenumbers


def normalize_phone(value):
    """Return canonical E.164, None for blank, or raise ValueError."""
    if value is None or not str(value).strip():
        return None
    try:
        parsed = phonenumbers.parse(str(value).strip(), None)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("invalid international phone number") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("invalid international phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def mask_phone(value):
    value = str(value or "")
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


@dataclass
class IdentityAuditResult:
    email_collisions: list = field(default_factory=list)
    username_collisions: list = field(default_factory=list)
    phone_collisions: list = field(default_factory=list)
    invalid_phones: list = field(default_factory=list)
    noncanonical_phones: list = field(default_factory=list)
    blank_phone_strings: list = field(default_factory=list)
    blank_emails: list = field(default_factory=list)
    blank_usernames: list = field(default_factory=list)

    @property
    def blocking(self):
        return any(
            (
                self.email_collisions,
                self.username_collisions,
                self.phone_collisions,
                self.invalid_phones,
                self.noncanonical_phones,
                self.blank_phone_strings,
                self.blank_emails,
                self.blank_usernames,
            )
        )


def audit_identity_rows(rows):
    result = IdentityAuditResult()
    emails = defaultdict(list)
    usernames = defaultdict(list)
    phones = defaultdict(list)

    for row in rows:
        record_id = str(row["id"])
        email = row.get("email")
        username = row.get("username")
        phone = row.get("phone_number")

        if email is None or not str(email).strip():
            result.blank_emails.append(record_id)
        else:
            emails[str(email).strip().casefold()].append(record_id)
        if username is None or not str(username).strip():
            result.blank_usernames.append(record_id)
        else:
            usernames[str(username).strip().casefold()].append(record_id)

        if phone is not None and not str(phone).strip():
            result.blank_phone_strings.append(record_id)
            continue
        try:
            normalized = normalize_phone(phone)
        except ValueError:
            result.invalid_phones.append({"id": record_id, "phone": mask_phone(phone)})
        else:
            if normalized is not None:
                phones[normalized].append(record_id)
                if str(phone).strip() != normalized:
                    result.noncanonical_phones.append(
                        {
                            "id": record_id,
                            "phone": mask_phone(phone),
                            "canonical": mask_phone(normalized),
                        }
                    )

    result.email_collisions = [ids for ids in emails.values() if len(ids) > 1]
    result.username_collisions = [ids for ids in usernames.values() if len(ids) > 1]
    result.phone_collisions = [
        {"phone": mask_phone(phone), "ids": ids} for phone, ids in phones.items() if len(ids) > 1
    ]
    return result
