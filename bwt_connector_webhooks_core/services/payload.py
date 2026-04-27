"""Lenient JSON payload decoders shared by inbound consumers.

Concrete connector addons (Stripe, Paddle, ...) need a single canonical
helper that turns a raw inbound ``payload_json`` string into a Python
``dict`` without raising. This module is the single source of truth.
"""

import json


def parse_json_object(raw):
    """Return a dict from a raw payload (str | bytes | dict | None).

    Returns an empty dict for falsy inputs, malformed JSON, or
    non-dict decoded values. Never raises.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {}
    if not isinstance(raw, str):
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}
