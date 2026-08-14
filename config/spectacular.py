"""Custom DRF spectacular schema classes."""

from __future__ import annotations

from drf_spectacular.openapi import AutoSchema


class LeagueOSAutoSchema(AutoSchema):
    """AutoSchema that derives the default tag from the view's app label."""

    def get_tags(self) -> list[str]:
        tags = super().get_tags()
        if tags and tags[0] == "api":
            view = getattr(self, "view", None)
            if view is not None:
                module = getattr(view.__class__, "__module__", "") or ""
                app_label = module.split(".", 1)[0] if "." in module else module
                if app_label:
                    tag = app_label.replace("_", " ").title()
                    special_cases = {
                        "Platformadmin": "PlatformAdmin",
                        "Kyc": "KYC",
                    }
                    tag = special_cases.get(tag, tag)
                    return [tag]
        return tags
