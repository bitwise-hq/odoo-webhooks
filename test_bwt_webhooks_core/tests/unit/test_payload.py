"""Unit tests for :mod:`bwt_webhooks_core.services.payload`.

Test suites in this module:

* :class:`TestSafeLoadJsonDict` — defensive JSON parsing that always
  returns a dictionary.
* :class:`TestSetPayloadPath` — dotted-path mutation helper used to
  inject computed values into outbound payloads.
"""

from .common import WebhookServiceTestCase

from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError
from odoo.addons.bwt_webhooks_core.services.payload import (
    safe_load_json_dict,
    set_payload_path,
)


class TestSafeLoadJsonDict(WebhookServiceTestCase):
    """``safe_load_json_dict`` parses JSON objects and swallows everything else."""

    def test_none_or_empty_returns_empty_dict(self):
        self.assertEqual(safe_load_json_dict(None), {})
        self.assertEqual(safe_load_json_dict(""), {})

    def test_valid_json_object(self):
        self.assertEqual(safe_load_json_dict('{"a": 1}'), {"a": 1})

    def test_non_object_returns_empty_dict(self):
        self.assertEqual(safe_load_json_dict("[]"), {})
        self.assertEqual(safe_load_json_dict("42"), {})

    def test_invalid_json_returns_empty_dict(self):
        self.assertEqual(safe_load_json_dict("{not json"), {})


class TestSetPayloadPath(WebhookServiceTestCase):
    """``set_payload_path`` writes values into a payload at a dotted path."""

    def test_empty_path_replaces_payload(self):
        self.assertEqual(set_payload_path({"a": 1}, "", "x"), "x")

    def test_assigns_top_level_key(self):
        self.assertEqual(set_payload_path({}, "a", 7), {"a": 7})

    def test_creates_intermediate_dicts(self):
        self.assertEqual(
            set_payload_path({}, "a.b.c", "v"),
            {"a": {"b": {"c": "v"}}},
        )

    def test_overwrites_existing_leaf(self):
        self.assertEqual(
            set_payload_path({"a": {"b": 1}}, "a.b", 2),
            {"a": {"b": 2}},
        )

    def test_collision_with_non_object_raises(self):
        with self.assertRaises(WebhookProcessingConfigurationError):
            set_payload_path({"a": 1}, "a.b.c", "v")

    def test_falsy_payload_treated_as_empty(self):
        self.assertEqual(set_payload_path(False, "a", 1), {"a": 1})
        self.assertEqual(set_payload_path(None, "a", 1), {"a": 1})

    def test_value_is_deep_copied_via_json(self):
        result = set_payload_path({}, "a", {"nested": [1, 2]})
        self.assertEqual(result, {"a": {"nested": [1, 2]}})
