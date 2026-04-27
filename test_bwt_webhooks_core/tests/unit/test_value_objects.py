"""Unit tests for :mod:`bwt_webhooks_core.services.value_objects`.

Test suites in this module:

* :class:`TestInboundMetadata` — read-only view over inbound metadata
  with safe defaults.
* :class:`TestOutboundRequestRoundtrip` — ``from_dict`` / ``to_dict`` /
  ``deep_copy`` semantics for outbound request value objects.
* :class:`TestOutboundRequestWithOverrides` — partial update semantics
  used by handler return values.
* :class:`TestOutboundRequestAssertValid` — invariant checks on body
  modes and multipart files.
* :class:`TestHandlerOutcomeFromRaw` — normalization of handler return
  values into a canonical :class:`HandlerOutcome`.
"""

from .common import WebhookServiceTestCase

from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError
from odoo.addons.bwt_webhooks_core.services.constants import (
    OUTCOME_CANCEL,
    OUTCOME_RETRY,
    OUTCOME_SEND,
)
from odoo.addons.bwt_webhooks_core.services.value_objects import (
    HandlerOutcome,
    InboundMetadata,
    OutboundRequest,
)


def _request(**overrides):
    base = {
        "target_url": "https://example/x",
        "http_method": "post",
        "request_body_mode": "json",
        "headers": {"X-A": "1"},
        "payload": {"k": "v"},
        "files": {},
    }
    base.update(overrides)
    return OutboundRequest(**base)


class TestInboundMetadata(WebhookServiceTestCase):
    """``InboundMetadata`` exposes a defensive read-only mapping view."""

    def test_get_falls_back_to_default(self):
        meta = InboundMetadata({"a": 1})
        self.assertEqual(meta.get("a"), 1)
        self.assertFalse(meta.get("b"))
        self.assertEqual(meta.get("b", "x"), "x")

    def test_as_dict_returns_copy(self):
        meta = InboundMetadata({"a": 1})
        snapshot = meta.as_dict()
        snapshot["a"] = 99
        self.assertEqual(meta.values["a"], 1)


class TestOutboundRequestRoundtrip(WebhookServiceTestCase):
    """``OutboundRequest`` round-trips through ``from_dict`` / ``to_dict``."""

    def test_from_dict_normalizes_method_and_body_mode(self):
        request = OutboundRequest.from_dict(
            {
                "target_url": "https://x",
                "http_method": "POST",
                "request_body_mode": " JSON ",
                "headers": {"X": 1},
                "payload": {"a": 1},
            }
        )
        self.assertEqual(request.http_method, "post")
        self.assertEqual(request.request_body_mode, "json")

    def test_from_dict_replaces_falsy_payload_with_empty_dict(self):
        request = OutboundRequest.from_dict({"payload": False})
        self.assertEqual(request.payload, {})

    def test_to_dict_round_trip(self):
        request = _request()
        again = OutboundRequest.from_dict(request.to_dict())
        self.assertEqual(again.to_dict(), request.to_dict())

    def test_deep_copy_isolates_mutations(self):
        request = _request(payload={"nested": {"a": 1}}, headers={"X": "y"})
        clone = request.deep_copy()
        clone.payload["nested"]["a"] = 99
        clone.headers["X"] = "z"
        self.assertEqual(request.payload["nested"]["a"], 1)
        self.assertEqual(request.headers["X"], "y")


class TestOutboundRequestWithOverrides(WebhookServiceTestCase):
    """``OutboundRequest.with_overrides`` applies handler-supplied patches."""

    def test_replaces_simple_fields(self):
        updated = _request().with_overrides(
            {
                "target_url": "https://new",
                "http_method": "PUT",
                "headers": {"X-B": "2"},
                "payload": {"k": "v2"},
                "request_body_mode": "FORM_URLENCODED",
            }
        )
        self.assertEqual(updated.target_url, "https://new")
        self.assertEqual(updated.http_method, "put")
        self.assertEqual(updated.headers, {"X-B": "2"})
        self.assertEqual(updated.payload, {"k": "v2"})
        self.assertEqual(updated.request_body_mode, "form_urlencoded")

    def test_legacy_transport_mode_alias_is_honored(self):
        updated = _request().with_overrides({"transport_mode": "multipart"})
        self.assertEqual(updated.request_body_mode, "multipart")

    def test_blank_body_mode_is_ignored(self):
        original = _request(request_body_mode="json")
        updated = original.with_overrides({"request_body_mode": ""})
        self.assertEqual(updated.request_body_mode, "json")


class TestOutboundRequestAssertValid(WebhookServiceTestCase):
    """``OutboundRequest.assert_valid`` enforces body-mode and file invariants."""

    def test_rejects_unknown_body_mode(self):
        bad = _request(request_body_mode="xml")
        with self.assertRaises(WebhookProcessingConfigurationError):
            bad.assert_valid()

    def test_rejects_non_dict_files(self):
        bad = _request(files=[("a", "b")])  # type: ignore[arg-type]
        with self.assertRaises(WebhookProcessingConfigurationError):
            bad.assert_valid()

    def test_accepts_default_modes(self):
        for mode in ("json", "form_urlencoded", "multipart"):
            _request(request_body_mode=mode).assert_valid()

    def test_multipart_file_keys_label(self):
        request = _request(files={"b": ("b.txt", b""), "a": ("a.txt", b"")})
        self.assertEqual(request.multipart_file_keys_label, "a, b")

    def test_multipart_file_keys_label_false_when_empty(self):
        self.assertFalse(_request().multipart_file_keys_label)


class TestHandlerOutcomeFromRaw(WebhookServiceTestCase):
    """``HandlerOutcome.from_raw`` canonicalizes handler return values."""

    def test_false_means_cancel(self):
        outcome = HandlerOutcome.from_raw(False, _request())
        self.assertEqual(outcome.status, OUTCOME_CANCEL)
        self.assertEqual(outcome.terminal_state, "canceled")

    def test_non_dict_means_send_with_base_request(self):
        base = _request()
        outcome = HandlerOutcome.from_raw("ignored", base)
        self.assertEqual(outcome.status, OUTCOME_SEND)
        self.assertEqual(outcome.request.to_dict(), base.to_dict())

    def test_dict_applies_overrides_and_status(self):
        outcome = HandlerOutcome.from_raw(
            {
                "status": OUTCOME_RETRY,
                "note": "later",
                "seconds": 30,
                "matched_rule_id": 7,
                "headers": {"X-New": "1"},
            },
            _request(),
        )
        self.assertEqual(outcome.status, OUTCOME_RETRY)
        self.assertEqual(outcome.note, "later")
        self.assertEqual(outcome.seconds, 30)
        self.assertEqual(outcome.matched_rule_id, 7)
        self.assertTrue(outcome.is_retry)
        self.assertIsNone(outcome.terminal_state)
        self.assertEqual(outcome.request.headers, {"X-New": "1"})

    def test_message_field_is_treated_as_note(self):
        outcome = HandlerOutcome.from_raw({"message": "hi"}, _request())
        self.assertEqual(outcome.note, "hi")
