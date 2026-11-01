"""The proxy setting must be explicit and preserve plain HTTP detection."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "trusted,scheme,expected",
    [
        ("False", "https", "False"),
        ("True", "https", "True"),
        ("True", "http", "False"),
    ],
)
def test_https_recognition_requires_trusted_proxy_opt_in(trusted, scheme, expected):
    env = dict(
        os.environ, DJANGO_SETTINGS_MODULE="config.settings", DJANGO_TRUST_PROXY_SSL_HEADER=trusted
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.test import RequestFactory; "
            f"print(RequestFactory().get('/', HTTP_X_FORWARDED_PROTO={scheme!r}).is_secure())",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert result.stdout.strip() == expected
