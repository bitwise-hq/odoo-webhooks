import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from odoo.exceptions import ValidationError

from ..exceptions import (
    WebhookFreshnessValidationError,
    WebhookProcessingConfigurationError,
    WebhookSignatureValidationError,
    WebhookValidationError,
)
from .common import WebhookEndpointTestCase


class TestWebhookEndpointSignature(WebhookEndpointTestCase):
    def test_endpoint_signature_configuration_constraints(self):
        endpoint = self._create_inbound_endpoint()

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "requires a semantic binding"
        ):
            endpoint.write({"delivery_identity_policy": "delivery_id"})

        self._create_binding(
            endpoint,
            semantic_name="delivery_id",
            value_key="delivery_key",
        )
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "no active value resolution rule"
        ):
            endpoint.write({"delivery_identity_policy": "delivery_id"})

        self._create_source(
            endpoint,
            field_name="delivery_key",
            source_kind="literal",
            literal_value="delivery-1",
        )
        endpoint.write({"delivery_identity_policy": "delivery_id"})

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "Replay identity policy"
        ):
            endpoint.write({"replay_identity_policy": "event_id"})

        self._create_binding(endpoint, semantic_name="event_id", value_key="event_key")
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "no active value resolution rule"
        ):
            endpoint.write({"replay_identity_policy": "event_id"})

        self._create_source(
            endpoint,
            field_name="event_key",
            source_kind="literal",
            literal_value="event-1",
        )
        endpoint.write({"replay_identity_policy": "event_id"})

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "primary signature secret"
        ):
            endpoint.write({"signature_verification_mode": "hmac"})

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "binding for Signature"
        ):
            endpoint.write(
                {
                    "signature_verification_mode": "hmac",
                    "signature_secret": "topsecret",
                    "signature_max_age_seconds": 0,
                    "signature_max_future_skew_seconds": 0,
                }
            )

        self._create_binding(
            endpoint, semantic_name="signature", value_key="signature_key"
        )
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "bound to signature_key"
        ):
            endpoint.write(
                {
                    "signature_verification_mode": "hmac",
                    "signature_secret": "topsecret",
                    "signature_max_age_seconds": 0,
                    "signature_max_future_skew_seconds": 0,
                }
            )

        self._create_source(
            endpoint,
            field_name="signature_key",
            source_kind="literal",
            literal_value="signature",
        )
        endpoint.write(
            {
                "signature_verification_mode": "hmac",
                "signature_secret": "topsecret",
                "signature_max_age_seconds": 0,
                "signature_max_future_skew_seconds": 0,
            }
        )

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "Signature Timestamp"
        ):
            endpoint.write({"signature_max_age_seconds": 60})

        self._create_binding(
            endpoint,
            semantic_name="signature_timestamp",
            value_key="signature_ts_key",
        )
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "bound to signature_ts_key"
        ):
            endpoint.write({"signature_max_age_seconds": 60})

        self._create_source(
            endpoint,
            field_name="signature_ts_key",
            source_kind="literal",
            literal_value="1700000000",
        )
        endpoint.write({"signature_max_age_seconds": 60})
        self.assertEqual(endpoint.signature_max_age_seconds, 60)

    def test_signature_part_validation_and_message_building(self):
        endpoint = self._create_inbound_endpoint(signature_message_joiner="|")
        invalid_endpoint = self._create_inbound_endpoint()
        body = b'{"ok": true}'
        headers = {"X-Request-Id": "req-1"}
        payload = {"data": {"id": "123"}}

        invalid_cases = [
            (
                {
                    "endpoint_id": endpoint.id,
                    "source_kind": "header",
                },
                "header name",
            ),
            (
                {
                    "endpoint_id": endpoint.id,
                    "source_kind": "header_param",
                    "header_name": "Stripe-Signature",
                },
                "parameter name",
            ),
            (
                {
                    "endpoint_id": endpoint.id,
                    "source_kind": "payload_path",
                },
                "payload path",
            ),
            (
                {
                    "endpoint_id": endpoint.id,
                    "source_kind": "literal",
                    "literal_value": False,
                },
                "literal value",
            ),
            (
                {
                    "endpoint_id": endpoint.id,
                    "source_kind": "computed",
                },
                "computed method",
            ),
        ]

        for vals, pattern in invalid_cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(ValidationError, pattern):
                    vals = dict(vals)
                    vals["endpoint_id"] = invalid_endpoint.id
                    self.env["webhook.endpoint.signature.part"].create(vals)

        self._create_signature_part(endpoint, source_kind="raw_body", sequence=10)
        self._create_signature_part(
            endpoint,
            source_kind="header",
            header_name="X-Request-Id",
            sequence=20,
        )
        self._create_signature_part(
            endpoint,
            source_kind="payload_path",
            payload_path="data.id",
            sequence=30,
        )
        self._create_signature_part(
            endpoint,
            source_kind="literal",
            literal_value="suffix",
            sequence=40,
        )

        self.assertEqual(
            endpoint._build_signature_message(body, headers, payload),
            '{"ok": true}|req-1|123|suffix',
        )

        required_endpoint = self._create_inbound_endpoint()
        self._create_signature_part(
            required_endpoint,
            source_kind="header",
            header_name="X-Missing",
            required=True,
        )

        with self.assertRaisesRegex(
            WebhookSignatureValidationError, "required signature message part"
        ):
            required_endpoint._build_signature_message(body, headers, payload)

        computed_endpoint = self._create_inbound_endpoint()
        self._create_signature_part(
            computed_endpoint,
            source_kind="computed",
            computed_method="does_not_exist",
        )

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "does_not_exist"
        ):
            computed_endpoint._build_signature_message(body, headers, payload)

    def test_signature_verification_freshness_and_identity(self):
        endpoint = self._create_inbound_endpoint(signature_message_joiner="|")
        body = b'{"ok": true}'
        payload = {"ok": True}

        self._create_source(
            endpoint,
            field_name="signature_key",
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="v1",
        )
        self._create_source(
            endpoint,
            field_name="signature_ts_key",
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="t",
        )
        self._create_source(
            endpoint,
            field_name="idem_key",
            source_kind="literal",
            literal_value="idem-1",
        )
        self._create_source(
            endpoint,
            field_name="event_key",
            source_kind="literal",
            literal_value="evt-1",
        )
        self._create_binding(
            endpoint,
            semantic_name="signature",
            value_key="signature_key",
        )
        self._create_binding(
            endpoint,
            semantic_name="signature_timestamp",
            value_key="signature_ts_key",
        )
        self._create_binding(
            endpoint,
            semantic_name="idempotency_key",
            value_key="idem_key",
        )
        self._create_binding(
            endpoint,
            semantic_name="event_id",
            value_key="event_key",
        )
        self._create_signature_part(endpoint, source_kind="raw_body", sequence=10)
        self._create_signature_part(
            endpoint,
            source_kind="literal",
            literal_value="suffix",
            sequence=20,
        )

        endpoint.write(
            {
                "signature_verification_mode": "hmac",
                "signature_secret": "topsecret",
                "signature_timestamp_format": "unix",
                "signature_max_age_seconds": 60,
                "signature_max_future_skew_seconds": 5,
            }
        )

        message = endpoint._build_signature_message(body, {}, payload)
        expected_signature = endpoint._compute_expected_signature("topsecret", message)
        current_timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        headers = {
            "Stripe-Signature": f"t={current_timestamp}, v1={expected_signature}"
        }
        metadata = endpoint._extract_inbound_metadata(body, headers, payload)

        endpoint._verify_signature(body, headers, payload, metadata)

        endpoint.write({"signature_timestamp_format": "unix_ms"})
        self.assertEqual(
            int(
                endpoint._parse_signature_timestamp(
                    str(int(current_timestamp) * 1000)
                ).timestamp()
            ),
            int(current_timestamp),
        )

        endpoint.write({"signature_timestamp_format": "iso8601"})
        self.assertEqual(
            endpoint._parse_signature_timestamp("2024-01-02T03:04:05Z"),
            datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        )

        endpoint.write({"signature_timestamp_format": "unix"})

        with self.assertRaisesRegex(
            WebhookFreshnessValidationError, "timestamp is required"
        ):
            endpoint._validate_signature_freshness(False)

        with self.assertRaisesRegex(WebhookFreshnessValidationError, "too old"):
            endpoint._validate_signature_freshness(
                str(
                    int(
                        (
                            datetime.now(timezone.utc) - timedelta(seconds=120)
                        ).timestamp()
                    )
                )
            )

        with self.assertRaisesRegex(
            WebhookFreshnessValidationError, "too far in the future"
        ):
            endpoint._validate_signature_freshness(
                str(
                    int(
                        (datetime.now(timezone.utc) + timedelta(seconds=30)).timestamp()
                    )
                )
            )

        endpoint.write(
            {
                "delivery_identity_policy": "idempotency_key",
                "replay_identity_policy": "event_id",
            }
        )
        metadata = endpoint._extract_inbound_metadata(body, headers, payload)

        self.assertEqual(
            endpoint._resolve_delivery_identity("body-sha", metadata),
            ("idem-1", "idempotency_key"),
        )
        self.assertEqual(
            endpoint._resolve_replay_identity(metadata),
            ("evt-1", "event_id"),
        )

        endpoint.write({"replay_identity_policy": "none"})
        self.assertEqual(endpoint._resolve_replay_identity({}), (False, False))

        with self.assertRaisesRegex(WebhookValidationError, "delivery identity"):
            endpoint._resolve_delivery_identity("body-sha", {})

        endpoint.write({"replay_identity_policy": "event_id"})

        with self.assertRaisesRegex(WebhookValidationError, "replay identity"):
            endpoint._resolve_replay_identity({})

    def test_endpoint_misc_helper_and_signature_branches(self):
        endpoint = self._create_inbound_endpoint()
        same_path_endpoint = self._create_inbound_endpoint(path="same-path")
        body = b'{"ok": true}'
        payload = {"data": {"items": [{"id": 1}]}}
        headers = {"Stripe-Signature": "v1=abc, v1=def"}

        same_path_endpoint.write({"path": "same-path"})
        self.assertEqual(same_path_endpoint.path, "same-path")

        self.assertFalse(endpoint._extract_header_value({"X-Test": "1"}, False))
        self.assertEqual(
            endpoint._extract_header_parameter_values(headers, False, "v1"),
            [],
        )
        self.assertEqual(
            endpoint._extract_header_parameter_values(
                headers, "Stripe-Signature", False
            ),
            [],
        )
        self.assertFalse(
            endpoint._extract_payload_path_value(payload, "data.items.foo")
        )
        self.assertFalse(endpoint._extract_payload_path_value(payload, "data.items.9"))
        self.assertFalse(endpoint._extract_payload_path_value("plain-text", "data"))
        self.assertFalse(endpoint._get_bound_value_key("missing"))
        self.assertFalse(endpoint._has_active_source_for_key("missing"))
        self.assertFalse(
            endpoint._extract_field_value("missing", body, headers, payload)
        )
        self.assertEqual(
            endpoint._build_signature_message(body, {}, payload), body.decode()
        )

        endpoint.write({"signature_encoding": "base64"})
        self.assertEqual(
            endpoint._compute_expected_signature("topsecret", "message"),
            base64.b64encode(
                hmac.new(
                    b"topsecret",
                    b"message",
                    getattr(hashlib, endpoint.signature_digest_algorithm),
                ).digest()
            ).decode("utf-8"),
        )
        self.assertFalse(endpoint._parse_signature_timestamp(False))
        endpoint.write({"signature_timestamp_format": "iso8601"})
        self.assertEqual(
            endpoint._parse_signature_timestamp("2024-01-02T03:04:05"),
            datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        )
        endpoint.write(
            {
                "signature_max_age_seconds": 0,
                "signature_max_future_skew_seconds": 0,
            }
        )
        endpoint._validate_signature_freshness(False)
        endpoint._verify_signature(body, {}, payload, {})

        multi_endpoint = self._create_inbound_endpoint()
        empty_endpoint = self._create_inbound_endpoint()
        self._create_source(
            multi_endpoint,
            field_name="signature_key",
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="v1",
        )
        self.assertEqual(
            multi_endpoint._extract_field_candidates(
                "signature_key",
                body,
                headers,
                payload,
                allow_multiple=True,
            ),
            ["abc", "def"],
        )
        self.assertEqual(empty_endpoint._get_configured_field_names(), [])
        self.assertEqual(
            empty_endpoint._extract_resolved_values(body, headers, payload), {}
        )
        self.assertEqual(
            empty_endpoint._extract_semantic_candidates(
                "signature", body, headers, payload
            ),
            [],
        )
        self.assertFalse(
            empty_endpoint._extract_semantic_value("signature", body, headers, payload)
        )
