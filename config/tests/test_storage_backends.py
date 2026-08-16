from django.core.files.storage import storages

from config.storage_backends import rewrite_presigned_url
from kyc.models import KYCVerificationAttempt


def test_rewrite_presigned_url_preserves_path_and_signature():
    internal = (
        "http://object-storage:8333/"
        "league-os-private/kyc_private/example.jpg"
        "?X-Amz-Signature=abc123"
    )

    rewritten = rewrite_presigned_url(
        internal,
        "https://leagueos.example/storage",
    )

    assert rewritten == (
        "https://leagueos.example/storage/"
        "league-os-private/kyc_private/example.jpg"
        "?X-Amz-Signature=abc123"
    )


def test_rewrite_presigned_url_is_noop_without_external_base():
    internal = "http://object-storage:8333/" "league-os-private/example.jpg"

    assert (
        rewrite_presigned_url(
            internal,
            "",
        )
        == internal
    )


def test_kyc_document_uses_private_storage():
    field = KYCVerificationAttempt._meta.get_field("document_image")

    assert field.storage is storages["private"]


def test_kyc_selfie_uses_private_storage():
    field = KYCVerificationAttempt._meta.get_field("selfie_image")

    assert field.storage is storages["private"]
