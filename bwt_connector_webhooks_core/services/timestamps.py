"""Timestamp normalization used for inbound conflict resolution."""

from datetime import datetime, timezone

from odoo import fields


def parse_iso_or_epoch_utc(value):
    """Return a tz-aware UTC ``datetime`` parsed from an ISO 8601 string or epoch.

    Accepts ``int``/``float`` epoch seconds and ISO 8601 strings (including
    the ``Z`` suffix). Naive datetime strings are rejected because they lead
    to ambiguous conflict resolution between Odoo and external systems.
    """
    if isinstance(value, bool) or value in (None, ""):
        raise ValueError("Missing timestamp value.")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("Empty timestamp value.")
        if text.isdigit():
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Naive datetimes are not accepted for conflict resolution.")
        return parsed.astimezone(timezone.utc)
    raise ValueError(f"Unsupported timestamp type: {type(value)}.")


def normalize_odoo_datetime_utc(value):
    """Return a tz-aware UTC ``datetime`` from an Odoo Datetime field value."""
    parsed = fields.Datetime.to_datetime(value)
    if not parsed:
        raise ValueError("Missing Odoo datetime for conflict comparison.")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
