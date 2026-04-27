"""Behavioral tests for :class:`webhook.inbound.endpoint`.

Each test exercises one observable behavior of the endpoint model so a
reader can use the test name as a one-line specification of what the
framework guarantees.
"""

from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.exceptions import (
    WebhookPayloadValidationError,
    WebhookSignatureValidationError,
    WebhookValidationError,
)
from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestWebhookPathSegmentNormalization(WebhookTestCase):
    """``_normalize_webhook_path_segment`` and its strict ``_validate_*`` sibling."""

    def setUp(self):
        super().setUp()
        self.endpoint_model = self.env["bwt.webhook.inbound.endpoint"]

    def test_normalize_strips_outer_whitespace_and_slashes(self):
        self.assertEqual(
            self.endpoint_model._normalize_webhook_path_segment("  /stripe-test/  "),
            "stripe-test",
        )

    def test_validate_returns_normalized_segment(self):
        self.assertEqual(
            self.endpoint_model._validate_webhook_path_segment(" /stripe-live/ "),
            "stripe-live",
        )

    def test_validate_allows_empty_segment_when_optional(self):
        self.assertEqual(
            self.endpoint_model._validate_webhook_path_segment("", required=False),
            "",
        )

    def test_validate_rejects_path_with_inner_slash(self):
        with self.assertRaisesRegex(ValidationError, "without slashes"):
            self.endpoint_model._validate_webhook_path_segment("bad/path")

    def test_validate_rejects_path_with_inner_whitespace(self):
        with self.assertRaisesRegex(ValidationError, "cannot contain whitespace"):
            self.endpoint_model._validate_webhook_path_segment("bad path")

    def test_validate_rejects_required_empty_segment(self):
        with self.assertRaisesRegex(ValidationError, "require a single URL path segment"):
            self.endpoint_model._validate_webhook_path_segment("")


class TestInboundEndpointPathField(WebhookTestCase):
    """``path`` field normalization and computed ``route_path``."""

    def test_path_with_outer_whitespace_is_normalized_on_create(self):
        endpoint = self.factory.inbound_endpoint(path=" helper-route ")

        self.assertEqual(endpoint.path, "helper-route")

    def test_route_path_combines_inbound_prefix_and_normalized_path(self):
        endpoint = self.factory.inbound_endpoint(path="helper-route")

        endpoint._compute_route_path()

        self.assertEqual(endpoint.route_path, "/webhooks/in/helper-route")

    def test_path_with_inner_slash_is_rejected_on_create(self):
        with self.assertRaisesRegex(ValidationError, "without slashes"):
            self.factory.inbound_endpoint(path="bad/path")

    def test_path_with_inner_whitespace_is_rejected_on_create(self):
        with self.assertRaisesRegex(ValidationError, "cannot contain whitespace"):
            self.factory.inbound_endpoint(path="bad path")


class TestInboundEndpointEventCounts(WebhookTestCase):
    """Computed counts and the ``action_view_*_events`` helpers."""

    def setUp(self):
        super().setUp()
        self.handler = self.factory.handler(direction="inbound")
        self.endpoint = self.factory.inbound_endpoint(handler=self.handler)

    def test_inbound_event_count_excludes_rejected_events(self):
        self.factory.inbound_event(self.endpoint, state="done")
        self.factory.inbound_event(self.endpoint, state="rejected")

        self.endpoint._compute_related_counts()

        self.assertEqual(self.endpoint.inbound_event_count, 1)

    def test_rejected_event_count_counts_only_rejected_events(self):
        self.factory.inbound_event(self.endpoint, state="done")
        self.factory.inbound_event(self.endpoint, state="rejected")

        self.endpoint._compute_related_counts()

        self.assertEqual(self.endpoint.rejected_event_count, 1)

    def test_action_view_inbound_events_excludes_rejected_state(self):
        action = self.endpoint.action_view_inbound_events()

        self.assertEqual(
            action["domain"],
            [("endpoint_id", "=", self.endpoint.id), ("state", "!=", "rejected")],
        )

    def test_action_view_rejected_events_filters_rejected_state(self):
        action = self.endpoint.action_view_rejected_events()

        self.assertEqual(
            action["domain"],
            [("endpoint_id", "=", self.endpoint.id), ("state", "=", "rejected")],
        )

    def test_action_view_events_default_endpoint_in_context(self):
        action = self.endpoint.action_view_inbound_events()

        self.assertEqual(action["context"], {"default_endpoint_id": self.endpoint.id})


class TestInboundEndpointHeaderHelpers(WebhookTestCase):
    """Header normalization and parameter extraction helpers."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_normalize_headers_lowercases_keys(self):
        self.assertEqual(
            self.endpoint._normalize_headers({"X-Test": "1"}),
            {"x-test": "1"},
        )

    def test_extract_header_value_is_case_insensitive(self):
        self.assertEqual(
            self.endpoint._extract_header_value({"X-Test": "1"}, "x-test"),
            "1",
        )

    def test_extract_header_parameter_values_returns_all_matches(self):
        signature_header = 't=1, v1="abc", v1=def'

        values = self.endpoint._extract_header_parameter_values({"Stripe-Signature": signature_header}, "Stripe-Signature", "v1")

        self.assertEqual(values, ["abc", "def"])


class TestInboundEndpointHandlerResolution(WebhookTestCase):
    """``_resolve_handler`` picks the matching handler from request metadata."""

    def setUp(self):
        super().setUp()
        self.default_handler = self.factory.handler(direction="inbound", code="default-selector")
        self.selected_handler = self.factory.handler(direction="inbound", code="route-selector")
        self.endpoint = self.factory.inbound_endpoint(handler=self.default_handler)

    def test_resolve_handler_returns_selected_handler_when_selector_matches(self):
        resolved = self.endpoint._resolve_handler({"handler_selector": "route-selector"})

        self.assertEqual(resolved, self.selected_handler)

    def test_resolve_handler_returns_default_handler_when_selector_missing(self):
        resolved = self.endpoint._resolve_handler({})

        self.assertEqual(resolved, self.default_handler)

    def test_resolve_handler_returns_default_handler_when_selector_unknown(self):
        resolved = self.endpoint._resolve_handler({"handler_selector": "no-such-selector"})

        self.assertEqual(resolved, self.default_handler)


class TestInboundEndpointInboundRequestValidation(WebhookTestCase):
    """``_validate_inbound_request`` enforces endpoint state and payload contract."""

    def test_archived_endpoint_rejects_inbound_request(self):
        endpoint = self.factory.inbound_endpoint(state="archived")

        with self.assertRaisesRegex(WebhookValidationError, "Archived endpoint"):
            endpoint._validate_inbound_request(b"{}", {}, {}, {})

    def test_payload_contract_rejects_top_level_array_when_object_required(self):
        endpoint = self.factory.inbound_endpoint(payload_contract="json_object")

        with self.assertRaisesRegex(WebhookPayloadValidationError, "top-level JSON object"):
            endpoint._validate_inbound_request(b"[]", {}, [], {})


class TestInboundEndpointSignatureVerification(WebhookTestCase):
    """``_verify_signature`` enforces presence and correctness of the HMAC signature."""

    def setUp(self):
        super().setUp()
        endpoint = self.factory.inbound_endpoint()
        self.factory.endpoint_source(
            endpoint,
            field_name="signature_key",
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="v1",
        )
        self.factory.semantic_binding(
            endpoint,
            semantic_name="signature",
            value_key="signature_key",
        )
        self.factory.signature_part(endpoint, source_kind="raw_body", sequence=10)
        endpoint.write(
            {
                "signature_verification_mode": "hmac",
                "signature_secret": "topsecret",
                "signature_max_age_seconds": 0,
                "signature_max_future_skew_seconds": 0,
            }
        )
        self.endpoint = endpoint

    def test_verify_signature_fails_when_signature_value_is_missing(self):
        with self.assertRaisesRegex(WebhookSignatureValidationError, "could not be resolved"):
            self.endpoint._verify_signature(b"{}", {}, {}, {})

    def test_verify_signature_fails_when_signature_does_not_match(self):
        wrong_signature_headers = {"Stripe-Signature": "v1=wrong"}

        with self.assertRaisesRegex(WebhookSignatureValidationError, "could not be verified"):
            self.endpoint._verify_signature(b"{}", wrong_signature_headers, {}, {})
