from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for the password change endpoint."""

    current_password = serializers.CharField(
        style={"input_type": "password"}, required=True, write_only=True
    )
    new_password = serializers.CharField(
        style={"input_type": "password"}, required=True, write_only=True
    )
    confirm_new_password = serializers.CharField(
        style={"input_type": "password"}, required=True, write_only=True
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError({"confirm_new_password": "New passwords must match."})
        return attrs

    def validate_new_password(self, value):
        """
        Validate password strength.
        """
        validate_password(value)
        return value
