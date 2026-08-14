"""Content sanitisation utilities for club management."""

from __future__ import annotations

import html
import logging
import re

logger = logging.getLogger(__name__)

# Allowed HTML tags for rich text content
ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "a",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "pre",
    "code",
    "hr",
}

# Allowed attributes for specific tags
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "title", "width", "height"},
    "p": {"class"},
    "div": {"class"},
}

# Allowed protocols for URLs
ALLOWED_PROTOCOLS = {"http", "https", "mailto"}

# Patterns that are always disallowed
DISALLOWED_PATTERNS = [
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"data:", re.IGNORECASE),
    re.compile(r"vbscript:", re.IGNORECASE),
]


def sanitise_html(content: str) -> str:
    """Sanitise HTML content to prevent XSS and malicious injection.

    Args:
        content: Raw HTML string.

    Returns:
        Sanitised HTML string safe for rendering.
    """
    if not content:
        return content

    # Remove null bytes
    content = content.replace("\x00", "")

    # Remove disallowed patterns
    for pattern in DISALLOWED_PATTERNS:
        content = pattern.sub("", content)

    # Parse and clean tags
    content = _strip_disallowed_tags(content)

    # Escape attribute values that contain suspicious content
    content = _sanitise_attributes(content)

    return content


def _strip_disallowed_tags(content: str) -> str:
    """Remove tags that are not in the allowed list."""
    result = []
    tag_buffer = []
    in_tag = False
    i = 0

    while i < len(content):
        char = content[i]

        if char == "<" and not in_tag:
            in_tag = True
            tag_buffer = ["<"]
            i += 1
            continue

        if in_tag:
            tag_buffer.append(char)

            if char == ">":
                tag_text = "".join(tag_buffer)
                tag_name = _extract_tag_name(tag_text)

                if tag_name in ALLOWED_TAGS:
                    result.append(tag_text)
                elif tag_name.startswith("/"):
                    closing_name = tag_name[1:]
                    if closing_name in ALLOWED_TAGS:
                        result.append(tag_text)

                in_tag = False
                tag_buffer = []
            i += 1
            continue

        result.append(char)
        i += 1

    return "".join(result)


def _extract_tag_name(tag_text: str) -> str:
    """Extract tag name from a tag string like <p class="x">."""
    match = re.match(r"</?(\w+)", tag_text)
    return match.group(1).lower() if match else ""


def _sanitise_attributes(content: str) -> str:
    """Sanitise attributes within allowed tags."""

    def clean_attrs(match):
        tag = match.group(0)
        tag_name = _extract_tag_name(tag)

        if tag_name not in ALLOWED_TAGS:
            return ""

        allowed = ALLOWED_ATTRIBUTES.get(tag_name, set())
        if not allowed:
            return f"<{tag_name}>"

        attr_pattern = re.compile(r'(\w+)=["\']([^"\']*)["\']')
        attrs = []
        for attr_match in attr_pattern.finditer(tag):
            attr_name = attr_match.group(1)
            attr_value = attr_match.group(2)

            if attr_name not in allowed:
                continue

            if attr_name == "href" or attr_name == "src":
                if not _is_safe_url(attr_value):
                    continue

            attrs.append(f'{attr_name}="{html.escape(attr_value, quote=True)}"')

        if attrs:
            return f"<{tag_name} {' '.join(attrs)}>"
        return f"<{tag_name}>"

    return re.sub(r"<[^>]+>", clean_attrs, content)


def _is_safe_url(url: str) -> bool:
    """Check if URL uses an allowed protocol."""
    url_lower = url.lower().strip()
    for protocol in ALLOWED_PROTOCOLS:
        if url_lower.startswith(f"{protocol}:"):
            return True
    return False


def sanitise_text(content: str) -> str:
    """Sanitise plain text content by escaping HTML entities.

    Args:
        content: Raw text string.

    Returns:
        HTML-escaped text string.
    """
    if not content:
        return content
    return html.escape(content, quote=True)
