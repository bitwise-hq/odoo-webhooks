"""JSON serialization helpers used to persist headers/payloads on records."""

import json

from odoo.tools import json_default


def serialize_headers(headers):
    """Return a deterministic JSON string for a header mapping.

    Sorted keys + indented output keep diffs readable in Odoo's audit
    trail. ``None`` is treated like an empty mapping.
    """
    return json.dumps(
        {str(key): str(value) for key, value in (headers or {}).items()},
        indent=2,
        sort_keys=True,
    )


def serialize_payload(payload):
    """Return a deterministic JSON string for an arbitrary payload value.

    Falls back to ``odoo.tools.json_default`` for non-JSON-native types
    such as ``datetime``.
    """
    return json.dumps(payload, default=json_default, indent=2, sort_keys=True)
