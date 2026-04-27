"""Pure header and payload extraction helpers.

These functions form the lowest layer of the inbound webhook value
extraction pipeline. They have no dependency on Odoo and operate on
plain Python types (``dict``, ``list``, ``str``, ``bytes``).
"""

import json
import re
from typing import Any


def normalize_headers(headers: dict) -> dict:
    """Return a copy of ``headers`` with lower-cased keys."""
    return {str(key).lower(): value for key, value in (headers or {}).items()}


def extract_header(headers: dict, header_name) -> Any:
    """Look up a header value case-insensitively.

    Returns ``False`` when ``header_name`` is empty or missing.
    """
    if not header_name:
        return False
    return normalize_headers(headers).get(str(header_name).lower(), False)


def extract_header_parameters(headers: dict, header_name, parameter_name) -> list:
    """Extract repeated ``key=value`` parameters from a structured header.

    Used for headers like ``Stripe-Signature: t=1,v1=abc,v1=def`` where
    multiple values for the same parameter must all be returned in
    declaration order.
    """
    if not header_name or not parameter_name:
        return []
    raw = extract_header(headers, header_name)
    if not raw:
        return []
    target = parameter_name.lower()
    matches = []
    for token in re.split(r"[;,]", str(raw)):
        token = token.strip()
        if not token or "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key.strip().lower() != target:
            continue
        matches.append(value.strip().strip('"'))
    return matches


def walk_payload_path(payload, path) -> Any:
    """Traverse ``payload`` along a dotted ``path``.

    * Missing keys, out-of-range indices, and non-traversable types
      uniformly return ``False``.
    * Container leaves (``dict`` / ``list``) are JSON-serialized with
      sorted keys so they can be hashed/compared deterministically.
    """
    if not path or payload in (False, None):
        return False
    current = payload
    for segment in path.split("."):
        if isinstance(current, list):
            if not segment.isdigit():
                return False
            index = int(segment)
            if index >= len(current):
                return False
            current = current[index]
        elif isinstance(current, dict):
            if segment not in current:
                return False
            current = current[segment]
        else:
            return False
    if isinstance(current, (dict, list)):
        return json.dumps(current, sort_keys=True)
    return current
