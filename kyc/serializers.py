from rest_framework import serializers
from profiles.models import Gender
from kyc.models import KYCVerification, KYCCheckResult, KYCConfiguration
from kyc.services.image_validation_service import KYCImageValidationService, KYCValidationError


class KYCSubmissionSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=KYCVerification.DocumentType.choices)
    document_country = serializers.CharField(max_length=3, default="UGA")
    document_image = serializers.FileField(required=True)
    selfie_image = serializers.FileField(required=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
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
    decision = serializers.ChoiceField(choices=["VERIFIED", "REJECTED", "REVIEW"])
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True)
