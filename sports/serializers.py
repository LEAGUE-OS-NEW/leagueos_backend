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
