from django.utils.text import slugify

from accounts.models import User


class UsernameService:
    default_username = "user"

    @classmethod
    def generate_unique_username(
        cls,
        *,
        email: str = "",
        phone_number: str = "",
        first_name: str = "",
        last_name: str = "",
    ) -> str:
        base_username = cls._build_base_username(
            email=email,
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
        )

        username_field = User._meta.get_field("username")
        max_length = username_field.max_length

        base_username = base_username[:max_length]
        candidate = base_username
        suffix_number = 2

        while User.objects.filter(
            username__iexact=candidate,
        ).exists():
            suffix = f"_{suffix_number}"
            available_length = max_length - len(suffix)

            candidate = f"{base_username[:available_length]}" f"{suffix}"
            suffix_number += 1

        return candidate

    @classmethod
    def _build_base_username(
        cls,
        *,
        email: str,
        phone_number: str,
        first_name: str,
        last_name: str,
    ) -> str:
        if email:
            raw_username = email.split("@", maxsplit=1)[0]
        elif first_name or last_name:
            raw_username = "_".join(
                value
                for value in [
                    first_name,
                    last_name,
                ]
                if value
            )
        elif phone_number:
            digits = "".join(character for character in phone_number if character.isdigit())
            raw_username = f"user_{digits}"
        else:
            raw_username = cls.default_username

        normalized_username = slugify(
            raw_username,
        ).replace("-", "_")

        return normalized_username or cls.default_username
