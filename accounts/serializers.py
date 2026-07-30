from rest_framework import serializers

from accounts.models import User


def build_response(success: bool, message: str, data=None, errors=None):
    payload = {"success": success, "message": message}
    if data is not None:
        payload["data"] = data
    if errors is not None:
        payload["errors"] = errors
    return payload


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(required=True, allow_blank=False)
    last_name = serializers.CharField(required=True, allow_blank=False)

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "password",
            "confirm_password",
        ]

    def validate(self, data):
        if data["password"] != data["confirm_password"]:
            raise serializers.ValidationError(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"confirm_password": ["Passwords do not match."]},
                )
            )

        channel = "SMS" if data.get("phone_number") else "EMAIL"
        if channel == "EMAIL":
            if not data.get("email"):
                raise serializers.ValidationError(
                    build_response(
                        success=False,
                        message="Invalid input",
                        errors={"email": ["Email is required for email verification."]},
                    )
                )
        elif channel == "SMS":
            if not data.get("phone_number"):
                raise serializers.ValidationError(
                    build_response(
                        success=False,
                        message="Invalid input",
                        errors={"phone_number": ["Phone number is required for SMS verification."]},
                    )
                )

        return data

    def validate_email(self, value):
        normalized = value.strip().lower()
        if User.objects.filter(email=normalized).exists():
            raise serializers.ValidationError(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"email": ["Email already registered."]},
                )
            )
        return normalized

    def validate_phone_number(self, value):
        if value and User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"phone_number": ["Phone number already registered."]},
                )
            )
        if not value:
            return value
        digits = "".join(filter(str.isdigit, value))
        if len(digits) != 10 or not digits.startswith("07"):
            raise serializers.ValidationError(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"phone_number": ["Enter a valid phone number (07xxxxxxxx)."]},
                )
            )
        return value

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")
        channel = "SMS" if validated_data.get("phone_number") else "EMAIL"
        validated_data["verification_channel"] = channel
        email = validated_data.get("email", "")
        validated_data.setdefault("username", email.split("@")[0])
        user = User.objects.create_user(password=password, **validated_data)
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "is_verified",
            "created_at",
        ]
        read_only_fields = fields


class RegistrationStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "email",
            "is_verified",
            "is_active",
            "verification_channel",
        ]
        read_only_fields = fields
