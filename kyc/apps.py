from django.apps import AppConfig
from django.conf import settings


class KYCConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kyc"
    verbose_name = "Identity Verification (KYC)"

    def ready(self):
        from kyc.models import KYCConfiguration

        try:
            config = KYCConfiguration.load()
            updates = {}
            field_map = {
                "KYC_MAX_ATTEMPTS": "max_attempts",
                "KYC_MAX_DOCUMENT_SIZE_MB": "max_document_size_mb",
                "KYC_FACE_MATCH_PASS_THRESHOLD": "face_match_pass_threshold",
                "KYC_FACE_MATCH_REVIEW_THRESHOLD": "face_match_review_threshold",
                "KYC_RISK_REVIEW_THRESHOLD": "risk_review_threshold",
                "KYC_RISK_REJECT_THRESHOLD": "risk_reject_threshold",
                "KYC_DOCUMENT_RETENTION_DAYS": "document_retention_days",
                "KYC_SELFIE_RETENTION_DAYS": "selfie_retention_days",
            }
            for setting_name, model_field in field_map.items():
                env_value = getattr(settings, setting_name, None)
                if env_value is not None and getattr(config, model_field) != env_value:
                    updates[model_field] = env_value

            if updates:
                for field, value in updates.items():
                    setattr(config, field, value)
                config.save(update_fields=list(updates.keys()))
        except Exception:
            pass

        try:
            from config.celery import discover_kyc_tasks

            discover_kyc_tasks()
        except Exception:
            pass
