"""JSON value serialization for outbound delivery context lines."""

import json


def json_serialize_value(value):
    """Return ``value`` as a JSON string, passing through existing strings."""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)
