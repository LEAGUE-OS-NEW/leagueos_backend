"""Serializers for the Club Admin match-data upload endpoint."""

from __future__ import annotations

from rest_framework import serializers

from clubs.services.match_data_service import REQUIRED_COLUMNS


class MatchDataUploadSerializer(serializers.Serializer):
    """Validates the multipart/form-data payload for the CSV upload endpoint.

    The only required field is ``file``.  The serializer rejects obviously
    wrong content types before the service layer attempts to parse anything.
    """

    file = serializers.FileField(
        help_text=(
            "CSV file containing match player statistics. "
            f"Required columns: {', '.join(sorted(REQUIRED_COLUMNS))}."
        ),
    )

    def validate_file(self, value):
        name = getattr(value, "name", "") or ""
        if not name.lower().endswith(".csv"):
            raise serializers.ValidationError(
                "Only CSV files are accepted (.csv extension required)."
            )
        # Guard against unreasonably large uploads (10 MB limit)
        max_bytes = 10 * 1024 * 1024
        if hasattr(value, "size") and value.size > max_bytes:
            raise serializers.ValidationError(
                f"File size exceeds the 10 MB limit "
                f"({value.size / (1024 * 1024):.1f} MB uploaded)."
            )
        return value


class MatchDataRowErrorSerializer(serializers.Serializer):
    """Represents a single row-level validation error in the response."""

    row = serializers.IntegerField(help_text="1-based row number in the CSV data (excluding header).")
    errors = serializers.ListField(
        child=serializers.CharField(),
        help_text="List of error messages for this row.",
    )


class MatchDataUploadResponseSerializer(serializers.Serializer):
    """Shape of a successful upload response."""

    success = serializers.BooleanField()
    message = serializers.CharField()
    records_received = serializers.IntegerField()
    records_processed = serializers.IntegerField()
    ingestion_id = serializers.UUIDField(allow_null=True)
    fixture_ids = serializers.ListField(child=serializers.UUIDField())


class MatchDataUploadErrorResponseSerializer(serializers.Serializer):
    """Shape of a failed upload response (validation errors)."""

    success = serializers.BooleanField(default=False)
    message = serializers.CharField()
    records_received = serializers.IntegerField()
    row_errors = MatchDataRowErrorSerializer(many=True)


class ClubFixtureSerializer(serializers.Serializer):
    """Lightweight fixture representation for the fixture-picker dropdown."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    starts_at = serializers.DateTimeField()
    status = serializers.CharField()
    competition = serializers.CharField(allow_null=True)
    home_team = serializers.CharField(allow_null=True)
    away_team = serializers.CharField(allow_null=True)
