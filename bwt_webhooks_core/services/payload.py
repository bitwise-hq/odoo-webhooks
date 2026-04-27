"""Pure JSON payload helpers used by outbound deliveries.

* :func:`safe_load_json_dict` — parse a stored JSON column into a dict
  while tolerating malformed or non-object content (returns ``{}``).
* :func:`set_payload_path` — assign ``value`` at a dotted ``target_path``
  inside a JSON-object ``payload``, creating intermediate objects.
"""

import json
from typing import Any

from odoo.tools import json_default

from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError


def safe_load_json_dict(value: Any) -> dict:
    """Return ``value`` parsed as a JSON object, or ``{}`` on any failure."""
    try:
        data = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def set_payload_path(payload: Any, target_path: str, value: Any) -> Any:
    """Assign ``value`` at ``target_path`` inside a JSON-object ``payload``.

    ``target_path`` is a dotted path; an empty path replaces the whole
    payload. Intermediate dicts are created as needed; collisions with
    non-object values raise
    :class:`WebhookProcessingConfigurationError`.
    """
    value = json.loads(json.dumps(value, default=json_default))
    if not target_path:
        return value
    if payload in (False, None):
        payload = {}
    if not isinstance(payload, dict):
        raise WebhookProcessingConfigurationError("Payload assignment requires a JSON object payload when using a nested target path.")
    path_parts = [part for part in target_path.split(".") if part]
    current = payload
    for part in path_parts[:-1]:
        current = current.setdefault(part, {})
        if not isinstance(current, dict):
            raise WebhookProcessingConfigurationError("Payload assignment path %s collides with a non-object value." % target_path)
    current[path_parts[-1]] = value
    return payload
