"""Validators for profile fields.

Provides sanitization and validation utilities for profile input data,
including XSS prevention and Unicode normalization.
"""

from __future__ import annotations

import html
import unicodedata

from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator


def sanitize_text(value: str) -> str:
    """Sanitize a string by stripping whitespace, preventing XSS, and normalizing Unicode.

    - Removes leading/trailing whitespace
    - Escapes HTML special characters to prevent XSS
    - Normalizes Unicode characters (NFKC)

    Args:
        value: Raw string input.

    Returns:
        Sanitized string.
    """
    value = value.strip()
    value = html.escape(value)
    value = unicodedata.normalize("NFKC", value)
    return value


def validate_text_field(value: str, max_length: int = 255) -> str:
    """Validate and sanitize a text field.

    Args:
        value: Raw string input.
        max_length: Maximum allowed length.

    Returns:
        Sanitized string.

    Raises:
        ValidationError: If the value exceeds max_length.
    """
    sanitized = sanitize_text(value)
    validator = MaxLengthValidator(max_length)
    validator(sanitized)
    return sanitized


def validate_no_xss(value: str) -> str:
    """Validate that a string does not contain potential XSS payloads.

    This is a defense-in-depth measure alongside the sanitize_text
    function. Checks for common XSS patterns.

    Args:
        value: Input string to check.

    Returns:
        Sanitized string with HTML escaped.

    Raises:
        ValidationError: If dangerous patterns are detected.
    """
    import re

    # Patterns that could indicate malicious input
    xss_patterns = [
        r"<script\b",
        r"javascript:",
        r"on\w+\s*=",
        r"<iframe\b",
        r"<object\b",
        r"<embed\b",
    ]

    lowered = value.lower()
    for pattern in xss_patterns:
        if re.search(pattern, lowered):
            raise ValidationError("Potentially malicious input detected.")

    return sanitize_text(value)


def validate_display_name(value: str) -> str:
    """Validate and sanitize a display name.

    Max length: 150 characters.
    """
    return validate_text_field(value, max_length=150)


def validate_city(value: str) -> str:
    """Validate and sanitize a city name.

    Max length: 100 characters.
    """
    return validate_text_field(value, max_length=100)


def validate_biography(value: str) -> str:
    """Validate and sanitize a biography.

    Max length: 500 characters.
    """
    return validate_text_field(value, max_length=500)
