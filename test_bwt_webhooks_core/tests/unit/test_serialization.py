"""Unit tests for :mod:`bwt_webhooks_core.services.serialization`.

Test suites in this module:

* :class:`TestSerializeHeaders` — deterministic, string-coerced JSON
  serialization of HTTP headers for storage and signing.
* :class:`TestSerializePayload` — JSON serialization of arbitrary
  payloads with stable key ordering and datetime support.
"""

import json
from .common import WebhookServiceTestCase
from datetime import datetime

from odoo.addons.bwt_webhooks_core.services.serialization import (
    serialize_headers,
    serialize_payload,
)


class TestSerializeHeaders(WebhookServiceTestCase):
    """``serialize_headers`` produces stable JSON with stringified values."""

    def test_handles_empty_or_none(self):
        self.assertEqual(json.loads(serialize_headers(None)), {})
        self.assertEqual(json.loads(serialize_headers({})), {})

    def test_sorts_keys_and_stringifies(self):
        headers = {"X-Z": 1, "A": True}
        text = serialize_headers(headers)
        # Sorted keys means "A" comes before "X-Z"
        self.assertLess(text.index('"A"'), text.index('"X-Z"'))
        loaded = json.loads(text)
        self.assertEqual(loaded, {"A": "True", "X-Z": "1"})


class TestSerializePayload(WebhookServiceTestCase):
    """``serialize_payload`` JSON-encodes payloads with sorted keys."""

    def test_serializes_datetimes_via_json_default(self):
        payload = {"when": datetime(2024, 1, 2, 3, 4, 5)}
        text = serialize_payload(payload)
        self.assertIn("2024-01-02", text)

    def test_sorts_keys(self):
        text = serialize_payload({"b": 1, "a": 2})
        self.assertLess(text.index('"a"'), text.index('"b"'))
