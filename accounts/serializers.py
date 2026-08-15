import phonenumbers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_slug
from rest_framework import serializers

from accounts.models import User
from accounts.services.username_service import UsernameService


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
    username = serializers.CharField(required=False, allow_blank=True, max_length=150)
    phone_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "username",
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

        return data

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def validate_username(self, value):
        value = value.strip()
        if not value:
            return ""
        try:
            validate_slug(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already in use.")
        return value

    def validate_email(self, value):
        normalized = value.strip().lower()
        existing = User.objects.filter(email__iexact=normalized).first()
        if existing and not existing.is_verified and not existing.is_active:
            self.context["existing_unverified_user"] = existing
            return normalized
        if existing:
            raise serializers.ValidationError(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"email": ["Email already registered."]},
                )
            )
        return normalized

    def validate_phone_number(self, value):
        if value is None or not value.strip():
            return None
        try:
            parsed = phonenumbers.parse(value.strip(), None)
        except phonenumbers.NumberParseException as exc:
            raise serializers.ValidationError("Enter a valid international phone number.") from exc
        if not phonenumbers.is_valid_number(parsed):
            raise serializers.ValidationError("Enter a valid international phone number.")
        normalized = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        if User.objects.filter(phone_number=normalized).exists():
            raise serializers.ValidationError(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"phone_number": ["Phone number already registered."]},
                )
            )
        return normalized

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")
        validated_data["verification_channel"] = "EMAIL"
        supplied_username = validated_data.get("username", "").strip()
        if not supplied_username:
            validated_data["username"] = UsernameService.generate_unique_username(
                email=validated_data.get("email", ""),
                phone_number=validated_data.get("phone_number", ""),
                first_name=validated_data.get("first_name", ""),
                last_name=validated_data.get("last_name", ""),
            )
        else:
            validated_data["username"] = supplied_username

        user = User.objects.create_user(
            password=password,
            **validated_data,
        )
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


class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(
        min_length=6,
        max_length=6,
    )


class AccountSetupCompleteSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(required=True, allow_blank=False)
    last_name = serializers.CharField(required=True, allow_blank=False)

    def validate(self, data):
        if data["password"] != data["confirm_password"]:
            raise serializers.ValidationError(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"confirm_password": ["Passwords do not match."]},
                )
            )
        return data

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()


class RegistrationStatusQuerySerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerificationDeliveryDataSerializer(serializers.Serializer):
    verification_required = serializers.BooleanField()
    verification_channel = serializers.ChoiceField(choices=["EMAIL"])
    destination = serializers.CharField()
    expires_in = serializers.IntegerField()
    resend_available_in = serializers.IntegerField()


class VerificationDeliveryResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = VerificationDeliveryDataSerializer()
