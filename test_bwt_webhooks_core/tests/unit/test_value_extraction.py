"""Unit tests for :mod:`bwt_webhooks_core.services.value_extraction`.

Test suites in this module:

* :class:`TestNormalizeHeaders` — lower-cased header view used for
  case-insensitive lookups.
* :class:`TestExtractHeader` — single header lookup with case-insensitive
  matching.
* :class:`TestExtractHeaderParameters` — named parameter extraction
  from comma-separated header values.
* :class:`TestWalkPayloadPath` — dotted-path traversal of nested payload
  dictionaries.
"""

from .common import WebhookServiceTestCase

from odoo.addons.bwt_webhooks_core.services.value_extraction import (
    extract_header,
    extract_header_parameters,
    normalize_headers,
    walk_payload_path,
)


class TestNormalizeHeaders(WebhookServiceTestCase):
    """``normalize_headers`` returns a lower-cased copy with last-write-wins."""

    def test_returns_empty_dict_for_falsy_input(self):
        self.assertEqual(normalize_headers(None), {})
        self.assertEqual(normalize_headers({}), {})

    def test_lowercases_keys_preserving_values(self):
        result = normalize_headers({"Content-Type": "application/json", "X-Foo": 7})
        self.assertEqual(result, {"content-type": "application/json", "x-foo": 7})

    def test_last_wins_on_duplicate_casing(self):
        result = normalize_headers({"X-Foo": "a", "x-foo": "b"})
        self.assertEqual(result, {"x-foo": "b"})


class TestExtractHeader(WebhookServiceTestCase):
    """``extract_header`` performs a case-insensitive header lookup."""

    def test_case_insensitive_lookup(self):
        headers = {"X-Stripe-Signature": "abc"}
        self.assertEqual(extract_header(headers, "x-stripe-signature"), "abc")
        self.assertEqual(extract_header(headers, "X-STRIPE-SIGNATURE"), "abc")

    def test_returns_false_when_missing(self):
        self.assertFalse(extract_header({"X-Foo": "y"}, "x-bar"))

    def test_returns_false_when_header_name_is_empty(self):
        self.assertFalse(extract_header({"X-Foo": "y"}, ""))


class TestExtractHeaderParameters(WebhookServiceTestCase):
    """``extract_header_parameters`` collects all values for a named parameter."""

    def test_extracts_named_parameter_returning_all_matches(self):
        headers = {
            "Stripe-Signature": "t=123,v1=abc,v1=def,v0=xyz",
        }
        result = extract_header_parameters(headers, "stripe-signature", "v1")
        self.assertEqual(result, ["abc", "def"])

    def test_returns_empty_list_when_header_missing(self):
        self.assertEqual(extract_header_parameters({}, "x-foo", "v1"), [])

    def test_returns_empty_list_when_parameter_missing(self):
        headers = {"X-Foo": "k=v"}
        self.assertEqual(extract_header_parameters(headers, "x-foo", "missing"), [])

    def test_returns_empty_list_when_header_name_is_empty(self):
        self.assertEqual(extract_header_parameters({"X-Foo": "k=v"}, "", "v1"), [])

    def test_skips_tokens_without_assignment(self):
        headers = {"X-Foo": "v1=abc, junkvalue, v1=def"}
        self.assertEqual(extract_header_parameters(headers, "x-foo", "v1"), ["abc", "def"])


class TestWalkPayloadPath(WebhookServiceTestCase):
    """``walk_payload_path`` resolves a dotted path against nested payloads."""

    def test_walks_nested_dicts(self):
        payload = {"a": {"b": {"c": 5}}}
        self.assertEqual(walk_payload_path(payload, "a.b.c"), 5)

    def test_returns_false_for_missing_keys(self):
        self.assertFalse(walk_payload_path({"a": {}}, "a.b.c"))

    def test_empty_path_returns_false(self):
        self.assertFalse(walk_payload_path({"a": 1}, ""))
