"""Admin configuration for the discovery module."""

from django.contrib import admin

from discovery.models import (
    AuditLog,
    ClubProfile,
    MatchBroadcast,
    MatchCentre,
    MatchLineup,
    MatchOfficial,
    MatchPlayerStatistic,
    MatchTeamStatistic,
    MatchTimelineEvent,
    News,
    NewsCategory,
    PlayerProfile,
    SearchAnalytics,
    SearchSuggestion,
    Season,
    SportsFeedIngestion,
    SportsFeedProvider,
    Venue,
)


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ["name", "country_code", "city", "is_active", "is_verified"]
    list_filter = ["is_active", "is_verified", "country_code"]
    search_fields = ["name", "city"]


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ["name", "sport", "competition", "is_active", "is_verified"]
    list_filter = ["is_active", "is_verified", "sport"]
    search_fields = ["name"]


@admin.register(ClubProfile)
class ClubProfileAdmin(admin.ModelAdmin):
    list_display = ["club", "stadium", "coach", "is_published", "is_verified"]
    list_filter = ["is_published", "is_verified"]
    search_fields = ["club__name", "stadium", "coach"]


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = ["participant", "club", "position", "status", "is_published", "is_verified"]
    list_filter = ["status", "is_published", "is_verified"]
    search_fields = ["participant__name", "position"]


@admin.register(NewsCategory)
class NewsCategoryAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "display_order", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["code", "name"]


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "status", "is_featured", "is_verified", "published_at"]
    list_filter = ["status", "is_featured", "is_verified", "category"]
    search_fields = ["title", "summary"]
    readonly_fields = ["slug", "published_at"]


@admin.register(MatchCentre)
class MatchCentreAdmin(admin.ModelAdmin):
    list_display = [
        "fixture",
        "result",
        "home_score",
        "away_score",
        "feed_status",
        "data_confidence",
    ]
    list_filter = ["feed_status", "is_verified"]
    search_fields = ["fixture__name"]


@admin.register(MatchLineup)
class MatchLineupAdmin(admin.ModelAdmin):
    list_display = ["match_centre", "side", "position", "is_starter"]
    list_filter = ["side", "is_starter"]


@admin.register(MatchPlayerStatistic)
class MatchPlayerStatisticAdmin(admin.ModelAdmin):
    list_display = ["match_centre", "participant", "stat_type", "value"]
    list_filter = ["stat_type"]


@admin.register(MatchTeamStatistic)
class MatchTeamStatisticAdmin(admin.ModelAdmin):
    list_display = ["match_centre", "participant", "stat_type", "value"]
    list_filter = ["stat_type"]


@admin.register(MatchTimelineEvent)
class MatchTimelineEventAdmin(admin.ModelAdmin):
    list_display = ["match_centre", "minute", "event_type", "description"]
    list_filter = ["event_type"]


@admin.register(MatchOfficial)
class MatchOfficialAdmin(admin.ModelAdmin):
    list_display = ["match_centre", "role", "name"]
    list_filter = ["role"]


@admin.register(MatchBroadcast)
class MatchBroadcastAdmin(admin.ModelAdmin):
    list_display = ["match_centre", "provider", "country_code"]
    list_filter = ["provider"]


@admin.register(SportsFeedProvider)
class SportsFeedProviderAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["code", "name"]


@admin.register(SportsFeedIngestion)
class SportsFeedIngestionAdmin(admin.ModelAdmin):
    list_display = ["provider", "status", "confidence", "is_verified", "started_at"]
    list_filter = ["status", "is_verified", "provider"]
    readonly_fields = ["started_at", "completed_at"]


@admin.register(SearchAnalytics)
class SearchAnalyticsAdmin(admin.ModelAdmin):
    list_display = ["query", "result_count", "is_empty", "is_failed", "timestamp"]
    list_filter = ["is_empty", "is_failed"]
    search_fields = ["query"]
    readonly_fields = ["timestamp"]


@admin.register(SearchSuggestion)
class SearchSuggestionAdmin(admin.ModelAdmin):
    list_display = ["suggestion_type", "entity_type", "display_name", "score", "is_active"]
    list_filter = ["suggestion_type", "entity_type", "is_active"]
    search_fields = ["display_name"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["action", "user", "entity_type", "entity_id", "timestamp"]
    list_filter = ["action", "entity_type"]
    search_fields = ["action", "entity_type"]
    readonly_fields = ["timestamp"]
