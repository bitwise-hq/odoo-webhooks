"""Identifier slugification used by webhook code/path generation."""

import re


def slugify_identifier(value):
    """Lowercase ``value``, collapse non-alphanumerics to ``-`` and trim ``-``."""
    slug = re.sub(r"[^0-9a-zA-Z]+", "-", str(value or "").strip().lower())
    return slug.strip("-")
