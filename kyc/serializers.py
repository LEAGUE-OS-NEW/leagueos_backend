from rest_framework import serializers
from profiles.models import Country, Gender
from kyc.models import KYCVerification, KYCCheckResult, KYCConfiguration
from kyc.services.image_validation_service import KYCImageValidationService, KYCValidationError


class KYCSubmissionSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=KYCVerification.DocumentType.choices)
    document_country = serializers.CharField(max_length=3, default="UGA")
    document_image = serializers.FileField(required=True)
    selfie_image = serializers.FileField(required=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    legal_name = serializers.CharField(max_length=255, trim_whitespace=True)
    identity_number = serializers.CharField(max_length=64, trim_whitespace=True, write_only=True)
    profile_country = serializers.SlugRelatedField(
        queryset=Country.objects.filter(is_active=True),
        slug_field="iso_code",
    )
    gender = serializers.PrimaryKeyRelatedField(
        queryset=Gender.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )

    def validate_document_country(self, value):
        val = value.upper().strip()
        if len(val) != 3:
            raise serializers.ValidationError("Country must be a 3-letter ISO code.")
        return val

    def validate_identity_number(self, value):
        normalized = "".join(value.split()).upper()
        if len(normalized) < 5:
            raise serializers.ValidationError("Identity number is too short.")
        return normalized

    def validate_legal_name(self, value):
        if len(value.split()) < 2:
            raise serializers.ValidationError("Enter your full legal name.")
        return " ".join(value.split())

    def validate(self, attrs):
        user = self.context.get("request").user if self.context.get("request") else None
        if user:
            account_name = " ".join(
                part for part in (user.first_name.strip(), user.last_name.strip()) if part
            ).casefold()
            if account_name and attrs["legal_name"].casefold() != account_name:
                raise serializers.ValidationError(
                    {"legal_name": "Legal name must match the authenticated account profile."}
                )
        if not attrs.get("date_of_birth"):
            profile = getattr(user, "profile", None)
            if profile is None or not profile.date_of_birth:
                raise serializers.ValidationError({"date_of_birth": "Date of birth is required."})
        return attrs

    def validate_document_image(self, value):
        try:
            raw_data = value.read()
            value.seek(0)
            KYCImageValidationService.validate_image(
                file_data=raw_data,
                filename=value.name,
                content_type=getattr(value, "content_type", None),
            )
        except KYCValidationError as e:
            raise serializers.ValidationError(f"Invalid document image: {e.message}") from e
        return value

    def validate_selfie_image(self, value):
        try:
            raw_data = value.read()
            value.seek(0)
            KYCImageValidationService.validate_image(
                file_data=raw_data,
                filename=value.name,
                content_type=getattr(value, "content_type", None),
            )
        except KYCValidationError as e:
            raise serializers.ValidationError(f"Invalid selfie image: {e.message}") from e
        return value


class KYCStatusResponseSerializer(serializers.ModelSerializer):
    can_retry = serializers.SerializerMethodField()
    attempts_count = serializers.SerializerMethodField()
    max_attempts = serializers.SerializerMethodField()
    submitted_at = serializers.DateTimeField(source="created_at", read_only=True)
    completed_at = serializers.DateTimeField(source="verification_completed_at", read_only=True)
    is_verified = serializers.SerializerMethodField()

    class Meta:
        model = KYCVerification
        fields = [
            "id",
            "status",
            "verification_source",
            "document_type",
            "document_country",
            "can_retry",
            "attempts_count",
            "max_attempts",
            "rejection_reason",
            "retry_reason",
            "submitted_at",
            "completed_at",
            "verified_at",
            "is_verified",
        ]

    def get_max_attempts(self, obj) -> int:
        return KYCConfiguration.load().max_attempts

    def get_attempts_count(self, obj) -> int:
        return obj.attempts.count()

    def get_can_retry(self, obj) -> bool:
        max_att = self.get_max_attempts(obj)
        current_count = self.get_attempts_count(obj)
        return (
            obj.status
            in [KYCVerification.Status.RETRY_REQUIRED, KYCVerification.Status.NOT_STARTED]
            and current_count < max_att
        )

    def get_is_verified(self, obj) -> bool:
        return obj.status == KYCVerification.Status.VERIFIED


class KYCCheckResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCCheckResult
        fields = [
            "id",
            "check_type",
            "status",
            "score",
            "confidence",
            "result_code",
            "details",
            "created_at",
        ]


class AdminKYCVerificationDetailSerializer(serializers.ModelSerializer):
    checks = KYCCheckResultSerializer(many=True, read_only=True)
    attempts_count = serializers.SerializerMethodField()
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = KYCVerification
        fields = [
            "id",
            "user_id",
            "user_email",
            "status",
            "verification_source",
            "document_type",
            "document_country",
            "document_number_last4",
            "document_expiry_date",
            "extracted_full_name",
            "extracted_date_of_birth",
            "extracted_nationality",
            "risk_level",
            "risk_score",
            "rejection_reason",
            "retry_reason",
            "verification_started_at",
            "verification_completed_at",
            "verified_at",
            "created_at",
            "updated_at",
            "attempts_count",
            "checks",
        ]

    def get_attempts_count(self, obj) -> int:
        return obj.attempts.count()


class AdminKYCReviewActionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["VERIFIED", "REJECTED"])
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True)
