from rest_framework import serializers

from sports.models import (
    Competition,
    EventParticipant,
    Participant,
    Sport,
    SportingEvent,
)


class SportPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sport
        fields = [
            "id",
            "name",
            "code",
            "slug",
        ]


class CompetitionPublicSerializer(serializers.ModelSerializer):
    sport = SportPublicSerializer(
        read_only=True,
    )

    class Meta:
        model = Competition
        fields = [
            "id",
            "name",
            "slug",
            "country_code",
            "sport",
        ]


class ParticipantPublicSerializer(serializers.ModelSerializer):
    sport = SportPublicSerializer(
        read_only=True,
    )

    class Meta:
        model = Participant
        fields = [
            "id",
            "name",
            "short_name",
            "slug",
            "kind",
            "country_code",
            "sport",
        ]


class EventParticipantPublicSerializer(serializers.ModelSerializer):
    participant = ParticipantPublicSerializer(
        read_only=True,
    )

    class Meta:
        model = EventParticipant
        fields = [
            "role",
            "position",
            "participant",
        ]


class SportingEventPublicSerializer(serializers.ModelSerializer):
    sport = SportPublicSerializer(
        read_only=True,
    )
    competition = CompetitionPublicSerializer(
        read_only=True,
    )
    participants = EventParticipantPublicSerializer(
        source="event_participants",
        many=True,
        read_only=True,
    )

    class Meta:
        model = SportingEvent
        fields = [
            "id",
            "name",
            "event_type",
            "status",
            "starts_at",
            "ends_at",
            "venue",
            "country_code",
            "sport",
            "competition",
            "participants",
        ]


class SportCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sport
        fields = ["id", "name", "code", "slug", "is_active"]
        read_only_fields = ["id"]
        extra_kwargs = {"slug": {"required": False}}


class CompetitionCreateSerializer(serializers.ModelSerializer):
    sport = serializers.PrimaryKeyRelatedField(queryset=Sport.objects.filter(is_active=True))

    class Meta:
        model = Competition
        fields = ["id", "sport", "name", "slug", "country_code", "is_active", "is_verified"]
        read_only_fields = ["id"]
        extra_kwargs = {
            "slug": {"required": False},
            # Admin-authored competitions are verified on creation — unlike the
            # scraped/seeded pipeline, there's no separate review step here.
            "is_verified": {"default": True},
        }


class CompetitionListQuerySerializer(serializers.Serializer):
    sport = serializers.UUIDField(
        required=False,
    )
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=180,
    )


class ParticipantListQuerySerializer(serializers.Serializer):
    sport = serializers.UUIDField(
        required=False,
    )
    kind = serializers.ChoiceField(
        choices=Participant.Kind.choices,
        required=False,
    )
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=180,
    )


class SportingEventListQuerySerializer(serializers.Serializer):
    sport = serializers.UUIDField(
        required=False,
    )
    competition = serializers.UUIDField(
        required=False,
    )
    participant = serializers.UUIDField(
        required=False,
    )
    status = serializers.ChoiceField(
        choices=SportingEvent.Status.choices,
        required=False,
    )
    event_type = serializers.ChoiceField(
        choices=SportingEvent.EventType.choices,
        required=False,
    )
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=255,
    )
