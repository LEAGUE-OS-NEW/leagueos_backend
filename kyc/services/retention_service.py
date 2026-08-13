import logging
from datetime import timedelta
from django.utils import timezone
from kyc.models import KYCConfiguration, KYCVerificationAttempt

logger = logging.getLogger(__name__)


class KYCRetentionService:
    """Service cleaning up expired KYC image attachments per data retention policy."""

    @classmethod
    def cleanup_expired_files(cls) -> int:
        config = KYCConfiguration.load()
        now = timezone.now()

        doc_cutoff = now - timedelta(days=config.document_retention_days)
        selfie_cutoff = now - timedelta(days=config.selfie_retention_days)

        cleaned_count = 0

        # Query completed attempts older than cutoff date
        attempts = KYCVerificationAttempt.objects.filter(
            created_at__lt=min(doc_cutoff, selfie_cutoff)
        ).exclude(document_image="", selfie_image="")

        for attempt in attempts:
            try:
                if attempt.created_at < doc_cutoff and attempt.document_image:
                    attempt.document_image.delete(save=False)
                    attempt.document_image = ""
                if attempt.created_at < selfie_cutoff and attempt.selfie_image:
                    attempt.selfie_image.delete(save=False)
                    attempt.selfie_image = ""

                attempt.save(update_fields=["document_image", "selfie_image"])
                cleaned_count += 1
            except Exception as e:
                logger.error("Error purging files for attempt %s: %s", attempt.id, e)

        logger.info("KYC retention service purged files for %d expired attempts.", cleaned_count)
        return cleaned_count
