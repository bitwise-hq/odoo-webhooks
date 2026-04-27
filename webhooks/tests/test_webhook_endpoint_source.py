import hashlib

from odoo.exceptions import ValidationError

from ..exceptions import WebhookProcessingConfigurationError
from .common import WebhookEndpointTestCase


class TestWebhookEndpointSource(WebhookEndpointTestCase):
    def test_source_line_validation_and_normalization(self):
        endpoint = self._create_inbound_endpoint()
        source = self._create_source(
            endpoint,
            field_name="  topic_key  ",
            literal_value="topic-value",
        )

        self.assertEqual(source.field_name, "topic_key")

        source.write({"field_name": "  normalized_key  "})

        self.assertEqual(source.field_name, "normalized_key")

        invalid_cases = [
            (
                {
                    "endpoint_id": endpoint.id,
                    "field_name": "   ",
                    "source_kind": "literal",
                    "literal_value": "value",
                },
                "field key",
            ),
            (
                {
                    "endpoint_id": endpoint.id,
                    "field_name": "header_key",
                    "source_kind": "header",
                },
                "header name",
            ),
            (
                {
                    "endpoint_id": endpoint.id,
                    "field_name": "header_param_key",
                    "source_kind": "header_param",
                    "header_name": "Stripe-Signature",
                },
                "parameter name",
            ),
            (
                {
                    "endpoint_id": endpoint.id,
                    "field_name": "payload_key",
                    "source_kind": "payload_path",
                },
                "payload path",
            ),
            (
                {
                    "endpoint_id": endpoint.id,
                    "field_name": "literal_key",
                    "source_kind": "literal",
                    "literal_value": False,
                },
                "literal value",
            ),
            (
                {
                    "endpoint_id": endpoint.id,
                    "field_name": "computed_key",
                    "source_kind": "computed",
                },
                "computed method",
            ),
        ]

        for vals, pattern in invalid_cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(ValidationError, pattern):
                    self.env["webhook.endpoint.source"].create(vals)

    def test_source_resolution_applies_fallbacks_transforms_and_computed_errors(self):
        endpoint = self._create_inbound_endpoint()
        computed_endpoint = self._create_inbound_endpoint()
        headers = {"X-Auth": "ToKen"}
        payload = {"data": {"items": [{"sku": "ABC"}]}}
        body = b"{}"

        self._create_source(
            endpoint,
            field_name="delivery_key",
            source_kind="header",
            header_name="X-Delivery",
            required=True,
        )
        self._create_source(
            endpoint,
            field_name="delivery_key",
            source_kind="literal",
            literal_value="fallback",
            candidate_sequence=20,
            joiner=":",
            sequence=1,
        )
        self._create_source(
            endpoint,
            field_name="delivery_key",
            source_kind="literal",
            literal_value="delivery",
            candidate_sequence=20,
            normalize_mode="upper",
            sequence=2,
        )
        self._create_source(
            endpoint,
            field_name="auth_hash",
            source_kind="header",
            header_name="X-Auth",
            normalize_mode="lower",
            hash_algorithm="sha256",
        )
        self._create_source(
            endpoint,
            field_name="payload_item",
            source_kind="payload_path",
            payload_path="data.items.0",
        )
        self._create_source(
            computed_endpoint,
            field_name="missing_computed",
            source_kind="computed",
            computed_method="does_not_exist",
        )

        resolved = endpoint._extract_resolved_values(body, headers, payload)

        self.assertEqual(
            endpoint._get_configured_field_names(),
            ["auth_hash", "delivery_key", "payload_item"],
        )
        self.assertEqual(resolved["delivery_key"], "fallback:DELIVERY")
        self.assertEqual(
            resolved["auth_hash"],
            hashlib.sha256("token".encode("utf-8")).hexdigest(),
        )
        self.assertEqual(resolved["payload_item"], '{"sku": "ABC"}')
        self.assertFalse(endpoint._extract_payload_path_value(payload, "data.items.9"))

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "does_not_exist"
        ):
            computed_endpoint._extract_field_value(
                "missing_computed", body, headers, payload
            )

    def test_semantic_binding_validation_and_metadata_extraction(self):
        endpoint = self._create_inbound_endpoint()
        headers = {
            "X-Topic": "orders.created",
            "Stripe-Signature": "t=1700000000, v1=abc, v1=def",
        }
        body = b"{}"
        payload = {}

        self._create_source(
            endpoint,
            field_name="  topic_key  ",
            source_kind="header",
            header_name="X-Topic",
        )
        self._create_source(
            endpoint,
            field_name="signature_key",
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="v1",
        )
        binding = self._create_binding(
            endpoint,
            semantic_name="topic",
            value_key="  topic_key  ",
        )
        self._create_binding(
            endpoint,
            semantic_name="signature",
            value_key="signature_key",
        )

        self.assertEqual(binding.value_key, "topic_key")

        binding.write({"value_key": "  renamed_topic_key  "})
        self.assertEqual(binding.value_key, "renamed_topic_key")

        self._create_source(
            endpoint,
            field_name="renamed_topic_key",
            source_kind="header",
            header_name="X-Topic",
        )

        resolved = endpoint._extract_resolved_values(body, headers, payload)
        metadata = endpoint._extract_inbound_metadata(
            body,
            headers,
            payload,
            resolved_values=resolved,
        )

        self.assertEqual(
            endpoint._get_semantic_binding_map(),
            {"signature": "signature_key", "topic": "renamed_topic_key"},
        )
        self.assertEqual(endpoint._get_bound_value_key("topic"), "renamed_topic_key")
        self.assertTrue(endpoint._has_active_source_for_key("renamed_topic_key"))
        self.assertEqual(
            endpoint._extract_semantic_candidates("signature", body, headers, payload),
            ["abc", "def"],
        )
        self.assertEqual(
            endpoint._extract_semantic_value(
                "topic",
                body,
                headers,
                payload,
                resolved_values=resolved,
            ),
            "orders.created",
        )
        self.assertEqual(metadata["topic"], "orders.created")
        self.assertEqual(metadata["signature"], "abc")
        self.assertFalse(metadata["event_type"])

        with self.assertRaisesRegex(ValidationError, "resolved key"):
            self.env["webhook.endpoint.semantic.binding"].create(
                {
                    "endpoint_id": endpoint.id,
                    "semantic_name": "event_type",
                    "value_key": "   ",
                }
            )
