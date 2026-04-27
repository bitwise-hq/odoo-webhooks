"""Behavioral tests for :class:`webhook.inbound.endpoint.semantic.binding`.

A semantic binding maps one of the framework's well-known semantic
names (``topic``, ``signature``, ``event_id``, ...) to a value
resolution key declared on the endpoint via a source record. The
binding is what lets a handler ask for "the topic" without knowing
which header or payload field actually carried the value.
"""

from odoo.exceptions import ValidationError

from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestSemanticBindingValueKeyNormalization(WebhookTestCase):
    """``value_key`` is trimmed of outer whitespace on create and write."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_value_key_is_trimmed_on_create(self):
        binding = self.factory.semantic_binding(self.endpoint, semantic_name="topic", value_key="  topic_key  ")

        self.assertEqual(binding.value_key, "topic_key")

    def test_value_key_is_trimmed_on_write(self):
        binding = self.factory.semantic_binding(self.endpoint, semantic_name="topic", value_key="initial")

        binding.value_key = "  renamed_topic_key  "

        self.assertEqual(binding.value_key, "renamed_topic_key")

    def test_write_without_value_key_does_not_touch_value_key(self):
        binding = self.factory.semantic_binding(self.endpoint, semantic_name="topic", value_key="topic_key")

        binding.semantic_name = "event_type"

        self.assertEqual(binding.semantic_name, "event_type")
        self.assertEqual(binding.value_key, "topic_key")


class TestSemanticBindingValueKeyValidation(WebhookTestCase):
    """A blank ``value_key`` is rejected at the database level."""

    def test_blank_value_key_is_rejected_on_create(self):
        endpoint = self.factory.inbound_endpoint()

        with self.assertRaisesRegex(ValidationError, "resolved key"):
            self.env["bwt.webhook.inbound.endpoint.semantic.binding"].create(
                {
                    "endpoint_id": endpoint.id,
                    "semantic_name": "event_type",
                    "value_key": "   ",
                }
            )


class TestEndpointSemanticBindingMap(WebhookTestCase):
    """``_get_semantic_binding_map`` exposes ``{semantic_name: value_key}``."""

    def test_binding_map_includes_every_configured_binding(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.semantic_binding(endpoint, semantic_name="topic", value_key="topic_key")
        self.factory.semantic_binding(endpoint, semantic_name="signature", value_key="signature_key")

        self.assertEqual(
            endpoint._get_semantic_binding_map(),
            {"topic": "topic_key", "signature": "signature_key"},
        )

    def test_get_bound_value_key_returns_value_key_for_binding(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.semantic_binding(endpoint, semantic_name="topic", value_key="topic_key")

        self.assertEqual(endpoint._get_bound_value_key("topic"), "topic_key")

    def test_get_bound_value_key_returns_falsy_for_missing_binding(self):
        endpoint = self.factory.inbound_endpoint()

        self.assertFalse(endpoint._get_bound_value_key("missing"))


class TestEndpointSemanticValueExtraction(WebhookTestCase):
    """``_extract_semantic_value`` and ``_extract_semantic_candidates`` resolve through the binding."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self.headers = {
            "X-Topic": "orders.created",
            "Stripe-Signature": "t=1700000000, v1=abc, v1=def",
        }
        self.body = b"{}"
        self.payload = {}
        self.factory.endpoint_source(
            self.endpoint,
            field_name="topic_key",
            source_kind="header",
            header_name="X-Topic",
        )
        self.factory.endpoint_source(
            self.endpoint,
            field_name="signature_key",
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="v1",
        )
        self.factory.semantic_binding(self.endpoint, semantic_name="topic", value_key="topic_key")
        self.factory.semantic_binding(self.endpoint, semantic_name="signature", value_key="signature_key")

    def test_extract_semantic_value_returns_resolved_value(self):
        resolved = self.endpoint._extract_resolved_values(self.body, self.headers, self.payload)

        value = self.endpoint._extract_semantic_value("topic", self.body, self.headers, self.payload, resolved_values=resolved)

        self.assertEqual(value, "orders.created")

    def test_extract_semantic_candidates_returns_all_matching_values(self):
        candidates = self.endpoint._extract_semantic_candidates("signature", self.body, self.headers, self.payload)

        self.assertEqual(candidates, ["abc", "def"])

    def test_unbound_semantic_returns_empty_candidates(self):
        empty_endpoint = self.factory.inbound_endpoint()

        self.assertEqual(
            empty_endpoint._extract_semantic_candidates("signature", self.body, self.headers, self.payload),
            [],
        )

    def test_unbound_semantic_returns_falsy_value(self):
        empty_endpoint = self.factory.inbound_endpoint()

        self.assertFalse(empty_endpoint._extract_semantic_value("signature", self.body, self.headers, self.payload))


class TestEndpointInboundMetadataExtraction(WebhookTestCase):
    """``_extract_inbound_metadata`` returns ``{semantic_name: value}`` with falsy entries for unbound names."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self.factory.endpoint_source(
            self.endpoint,
            field_name="topic_key",
            source_kind="header",
            header_name="X-Topic",
        )
        self.factory.semantic_binding(self.endpoint, semantic_name="topic", value_key="topic_key")

    def test_metadata_contains_resolved_value_for_bound_semantic(self):
        headers = {"X-Topic": "orders.created"}
        body = b"{}"
        payload = {}
        resolved = self.endpoint._extract_resolved_values(body, headers, payload)

        metadata = self.endpoint._extract_inbound_metadata(body, headers, payload, resolved_values=resolved)

        self.assertEqual(metadata["topic"], "orders.created")

    def test_metadata_contains_falsy_entry_for_unbound_semantic(self):
        headers = {"X-Topic": "orders.created"}
        body = b"{}"
        payload = {}
        resolved = self.endpoint._extract_resolved_values(body, headers, payload)

        metadata = self.endpoint._extract_inbound_metadata(body, headers, payload, resolved_values=resolved)

        self.assertFalse(metadata["event_type"])
