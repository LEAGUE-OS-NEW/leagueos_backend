from django.contrib import admin

from profiles.models import Club, Country, Gender, Language, Profile, Timezone


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ["name", "iso_code", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "iso_code"]


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "code"]


@admin.register(Timezone)
class TimezoneAdmin(admin.ModelAdmin):
    list_display = ["timezone_name", "utc_offset", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["timezone_name"]


@admin.register(Gender)
class GenderAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "code"]


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug"]


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "display_name", "country", "favourite_club"]
    list_select_related = ["user", "country", "favourite_club"]
    search_fields = ["user__email", "display_name"]
