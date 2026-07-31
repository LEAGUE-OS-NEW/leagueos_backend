from django.contrib import admin

from sports.models import (
    Competition,
    EventParticipant,
    Participant,
    Sport,
    SportingEvent,
)


@admin.register(Sport)
class SportAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "is_active",
    )
    list_filter = ("is_active",)
    search_fields = (
        "name",
        "code",
    )
    prepopulated_fields = {
        "slug": ("name",),
    }


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "sport",
        "country_code",
        "is_active",
        "is_verified",
    )
    list_filter = (
        "sport",
        "country_code",
        "is_active",
        "is_verified",
    )
    search_fields = (
        "name",
        "source_reference",
    )
    prepopulated_fields = {
        "slug": ("name",),
    }


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "kind",
        "sport",
        "country_code",
        "is_active",
        "is_verified",
    )
    list_filter = (
        "kind",
        "sport",
        "country_code",
        "is_active",
        "is_verified",
    )
    search_fields = (
        "name",
        "short_name",
        "source_reference",
    )
    prepopulated_fields = {
        "slug": ("name",),
    }


class EventParticipantInline(admin.TabularInline):
    model = EventParticipant
    extra = 0
    autocomplete_fields = ("participant",)


@admin.register(SportingEvent)
class SportingEventAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "sport",
        "competition",
        "event_type",
        "starts_at",
        "status",
        "is_verified",
    )
    list_filter = (
        "sport",
        "competition",
        "event_type",
        "status",
        "is_verified",
    )
    search_fields = (
        "name",
        "source_reference",
        "event_participants__participant__name",
    )
    autocomplete_fields = (
        "sport",
        "competition",
    )
    inlines = (EventParticipantInline,)


@admin.register(EventParticipant)
class EventParticipantAdmin(admin.ModelAdmin):
    list_display = (
        "event",
        "participant",
        "role",
        "position",
    )
    list_filter = (
        "role",
        "event__sport",
    )
    search_fields = (
        "event__name",
        "participant__name",
    )
    autocomplete_fields = (
        "event",
        "participant",
    )
