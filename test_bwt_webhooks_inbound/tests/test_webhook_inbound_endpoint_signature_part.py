"""Behavioral tests for :class:`webhook.inbound.endpoint.signature.part`.

The signature part record describes one segment of the canonical
message that a webhook signature is computed over. The endpoint owns
the global signature configuration; the parts describe how to build
the bytes that get fed to the HMAC.
"""

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.exceptions import (
    WebhookFreshnessValidationError,
    WebhookProcessingConfigurationError,
    WebhookSignatureValidationError,
    WebhookValidationError,
)
from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


HMAC_SECRET = "topsecret"


class TestSignaturePartRequiredFieldsByKind(WebhookTestCase):
    """A signature part of each ``source_kind`` rejects creation when its required field is missing."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self.signature_part_model = self.env["bwt.webhook.inbound.endpoint.signature.part"]

    def test_header_part_without_header_name_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "header name"):
            self.signature_part_model.create({"endpoint_id": self.endpoint.id, "source_kind": "header"})

    def test_header_param_part_without_parameter_name_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "parameter name"):
            self.signature_part_model.create(
                {
                    "endpoint_id": self.endpoint.id,
                    "source_kind": "header_param",
                    "header_name": "Stripe-Signature",
                }
            )

    def test_payload_path_part_without_payload_path_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "payload path"):
            self.signature_part_model.create({"endpoint_id": self.endpoint.id, "source_kind": "payload_path"})

    def test_literal_part_without_literal_value_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "literal value"):
            self.signature_part_model.create(
                {
                    "endpoint_id": self.endpoint.id,
                    "source_kind": "literal",
                    "literal_value": False,
                }
            )

    def test_computed_part_without_method_name_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "computed method"):
            self.signature_part_model.create({"endpoint_id": self.endpoint.id, "source_kind": "computed"})


class TestEndpointSignatureMessageBuilding(WebhookTestCase):
    """``_build_signature_message`` joins parts in sequence using the configured joiner."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint(signature_message_joiner="|")
        self.body = b'{"ok": true}'
        self.headers = {"X-Request-Id": "req-1"}
        self.payload = {"data": {"id": "123"}}

    def test_message_with_no_parts_falls_back_to_raw_body(self):
        empty_endpoint = self.factory.inbound_endpoint()

        message = empty_endpoint._build_signature_message(self.body, self.headers, self.payload)

        self.assertEqual(message, self.body.decode())

    def test_parts_are_joined_in_sequence_order_with_configured_joiner(self):
        self.factory.signature_part(self.endpoint, source_kind="raw_body", sequence=10)
        self.factory.signature_part(
            self.endpoint,
            source_kind="header",
            header_name="X-Request-Id",
            sequence=20,
        )
        self.factory.signature_part(
            self.endpoint,
            source_kind="payload_path",
            payload_path="data.id",
            sequence=30,
        )
        self.factory.signature_part(
            self.endpoint,
            source_kind="literal",
            literal_value="suffix",
            sequence=40,
        )

        message = self.endpoint._build_signature_message(self.body, self.headers, self.payload)

        self.assertEqual(message, '{"ok": true}|req-1|123|suffix')


class TestEndpointSignatureRequiredAndComputedParts(WebhookTestCase):
    """Required parts must resolve and computed parts must point to a real method."""

    def test_required_part_that_does_not_resolve_raises(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.signature_part(
            endpoint,
            source_kind="header",
            header_name="X-Missing",
            required=True,
        )

        with self.assertRaisesRegex(WebhookSignatureValidationError, "required signature message part"):
            endpoint._build_signature_message(b"{}", {}, {})

    def test_computed_part_pointing_to_missing_method_raises(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.signature_part(
            endpoint,
            source_kind="computed",
            computed_method="does_not_exist",
        )

        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "does_not_exist"):
            endpoint._build_signature_message(b"{}", {}, {})

    def test_optional_part_with_unresolved_value_is_skipped(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.signature_part(
            endpoint,
            source_kind="header",
            header_name="X-Missing",
            required=False,
            sequence=10,
        )
        self.factory.signature_part(
            endpoint,
            source_kind="literal",
            literal_value="payload",
            sequence=20,
        )

        self.assertEqual(endpoint._build_signature_message(b"{}", {}, {}), "payload")


class TestEndpointSignatureTimestampParsing(WebhookTestCase):
    """``_parse_signature_timestamp`` decodes the configured timestamp format."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_unix_format_returns_aware_utc_datetime(self):
        self.endpoint.signature_timestamp_format = "unix"

        parsed = self.endpoint._parse_signature_timestamp("1700000000")

        self.assertEqual(int(parsed.timestamp()), 1700000000)

    def test_unix_ms_format_strips_trailing_milliseconds(self):
        self.endpoint.signature_timestamp_format = "unix_ms"

        parsed = self.endpoint._parse_signature_timestamp("1700000000000")

        self.assertEqual(int(parsed.timestamp()), 1700000000)

    def test_iso8601_format_with_z_suffix_returns_utc_datetime(self):
        self.endpoint.signature_timestamp_format = "iso8601"

        parsed = self.endpoint._parse_signature_timestamp("2024-01-02T03:04:05Z")

        self.assertEqual(parsed, datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc))

    def test_iso8601_format_without_zone_returns_utc_datetime(self):
        self.endpoint.signature_timestamp_format = "iso8601"

        parsed = self.endpoint._parse_signature_timestamp("2024-01-02T03:04:05")

        self.assertEqual(parsed, datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc))

    def test_falsy_input_returns_falsy_value(self):
        self.assertFalse(self.endpoint._parse_signature_timestamp(False))


class TestEndpointSignatureFreshness(WebhookTestCase):
    """``_validate_signature_freshness`` enforces the configured age and skew."""

    MAX_AGE_SECONDS = 60
    MAX_SKEW_SECONDS = 5

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint(
            signature_max_age_seconds=self.MAX_AGE_SECONDS,
            signature_max_future_skew_seconds=self.MAX_SKEW_SECONDS,
            signature_timestamp_format="unix",
        )

    def test_missing_timestamp_when_max_age_is_set_raises(self):
        with self.assertRaisesRegex(WebhookFreshnessValidationError, "timestamp is required"):
            self.endpoint._validate_signature_freshness(False)

    def test_timestamp_older_than_max_age_raises(self):
        too_old = datetime.now(timezone.utc) - timedelta(seconds=self.MAX_AGE_SECONDS * 2)

        with self.assertRaisesRegex(WebhookFreshnessValidationError, "too old"):
            self.endpoint._validate_signature_freshness(str(int(too_old.timestamp())))

    def test_timestamp_beyond_future_skew_raises(self):
        too_future = datetime.now(timezone.utc) + timedelta(seconds=self.MAX_SKEW_SECONDS * 6)

        with self.assertRaisesRegex(WebhookFreshnessValidationError, "too far in the future"):
            self.endpoint._validate_signature_freshness(str(int(too_future.timestamp())))

    def test_freshness_check_is_skipped_when_max_age_and_skew_are_zero(self):
        unconstrained_endpoint = self.factory.inbound_endpoint(
            signature_max_age_seconds=0,
            signature_max_future_skew_seconds=0,
        )

        unconstrained_endpoint._validate_signature_freshness(False)


class TestEndpointSignatureEncoding(WebhookTestCase):
    """``signature_encoding`` controls the encoding of the expected signature."""

    def test_base64_encoding_returns_base64_hmac(self):
        endpoint = self.factory.inbound_endpoint(signature_encoding="base64")
        message = "message"

        computed = endpoint._compute_expected_signature(HMAC_SECRET, message)

        expected = base64.b64encode(
            hmac.new(
                HMAC_SECRET.encode("utf-8"),
                message.encode("utf-8"),
                getattr(hashlib, endpoint.signature_digest_algorithm),
            ).digest()
        ).decode("utf-8")
        self.assertEqual(computed, expected)


class TestEndpointDeliveryIdentityPolicyConstraints(WebhookTestCase):
    """Delivery identity policy requires a binding and a value resolution rule."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_policy_change_without_binding_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "requires a semantic binding"):
            self.endpoint.delivery_identity_policy = "delivery_id"

    def test_policy_change_without_active_resolution_rule_is_rejected(self):
        self.factory.semantic_binding(self.endpoint, semantic_name="delivery_id", value_key="delivery_key")

        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "no active value resolution rule"):
            self.endpoint.delivery_identity_policy = "delivery_id"

    def test_policy_change_succeeds_when_binding_and_rule_are_present(self):
        self.factory.semantic_binding(self.endpoint, semantic_name="delivery_id", value_key="delivery_key")
        self.factory.endpoint_source(self.endpoint, field_name="delivery_key", literal_value="delivery-1")

        self.endpoint.delivery_identity_policy = "delivery_id"

        self.assertEqual(self.endpoint.delivery_identity_policy, "delivery_id")


class TestEndpointReplayIdentityPolicyConstraints(WebhookTestCase):
    """Replay identity policy requires a binding and a value resolution rule."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_policy_change_without_binding_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "Replay identity policy"):
            self.endpoint.replay_identity_policy = "event_id"

    def test_policy_change_without_active_resolution_rule_is_rejected(self):
        self.factory.semantic_binding(self.endpoint, semantic_name="event_id", value_key="event_key")

        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "no active value resolution rule"):
            self.endpoint.replay_identity_policy = "event_id"

    def test_policy_change_succeeds_when_binding_and_rule_are_present(self):
        self.factory.semantic_binding(self.endpoint, semantic_name="event_id", value_key="event_key")
        self.factory.endpoint_source(self.endpoint, field_name="event_key", literal_value="event-1")

        self.endpoint.replay_identity_policy = "event_id"

        self.assertEqual(self.endpoint.replay_identity_policy, "event_id")


class TestEndpointSignatureModeConstraints(WebhookTestCase):
    """Enabling ``signature_verification_mode`` requires secret, binding and rule."""

    SIGNATURE_KEY = "signature_key"

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_hmac_mode_without_secret_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "primary signature secret"):
            self.endpoint.signature_verification_mode = "hmac"

    def test_hmac_mode_without_signature_binding_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "binding for Signature"):
            self.endpoint.write(
                {
                    "signature_verification_mode": "hmac",
                    "signature_secret": HMAC_SECRET,
                    "signature_max_age_seconds": 0,
                    "signature_max_future_skew_seconds": 0,
                }
            )

    def test_hmac_mode_without_signature_resolution_rule_is_rejected(self):
        self.factory.semantic_binding(
            self.endpoint,
            semantic_name="signature",
            value_key=self.SIGNATURE_KEY,
        )

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError,
            f"bound to {self.SIGNATURE_KEY}",
        ):
            self.endpoint.write(
                {
                    "signature_verification_mode": "hmac",
                    "signature_secret": HMAC_SECRET,
                    "signature_max_age_seconds": 0,
                    "signature_max_future_skew_seconds": 0,
                }
            )

    def test_hmac_mode_succeeds_when_binding_and_rule_are_present(self):
        self.factory.semantic_binding(
            self.endpoint,
            semantic_name="signature",
            value_key=self.SIGNATURE_KEY,
        )
        self.factory.endpoint_source(
            self.endpoint,
            field_name=self.SIGNATURE_KEY,
            literal_value="signature",
        )

        self.endpoint.write(
            {
                "signature_verification_mode": "hmac",
                "signature_secret": HMAC_SECRET,
                "signature_max_age_seconds": 0,
                "signature_max_future_skew_seconds": 0,
            }
        )

        self.assertEqual(self.endpoint.signature_verification_mode, "hmac")


class TestEndpointSignatureTimestampPolicyConstraints(WebhookTestCase):
    """``signature_max_age_seconds`` > 0 requires a signature_timestamp binding and rule."""

    SIGNATURE_TIMESTAMP_KEY = "signature_ts_key"

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self._enable_hmac_mode_minimal_setup()

    def _enable_hmac_mode_minimal_setup(self):
        self.factory.semantic_binding(
            self.endpoint,
            semantic_name="signature",
            value_key="signature_key",
        )
        self.factory.endpoint_source(self.endpoint, field_name="signature_key", literal_value="signature")
        self.endpoint.write(
            {
                "signature_verification_mode": "hmac",
                "signature_secret": HMAC_SECRET,
                "signature_max_age_seconds": 0,
                "signature_max_future_skew_seconds": 0,
            }
        )

    def test_max_age_without_timestamp_binding_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "Signature Timestamp"):
            self.endpoint.signature_max_age_seconds = 60

    def test_max_age_without_timestamp_rule_is_rejected(self):
        self.factory.semantic_binding(
            self.endpoint,
            semantic_name="signature_timestamp",
            value_key=self.SIGNATURE_TIMESTAMP_KEY,
        )

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError,
            f"bound to {self.SIGNATURE_TIMESTAMP_KEY}",
        ):
            self.endpoint.signature_max_age_seconds = 60

    def test_max_age_succeeds_when_timestamp_binding_and_rule_are_present(self):
        self.factory.semantic_binding(
            self.endpoint,
            semantic_name="signature_timestamp",
            value_key=self.SIGNATURE_TIMESTAMP_KEY,
        )
        self.factory.endpoint_source(
            self.endpoint,
            field_name=self.SIGNATURE_TIMESTAMP_KEY,
            literal_value="1700000000",
        )

        self.endpoint.signature_max_age_seconds = 60

        self.assertEqual(self.endpoint.signature_max_age_seconds, 60)


def _stripe_style_endpoint(factory, *, signature_max_age=0, signature_max_skew=0):
    """Build an endpoint with a Stripe-style signature/identity setup."""
    endpoint = factory.inbound_endpoint(signature_message_joiner="|")
    factory.endpoint_source(
        endpoint,
        field_name="signature_key",
        source_kind="header_param",
        header_name="Stripe-Signature",
        header_param_name="v1",
    )
    factory.endpoint_source(
        endpoint,
        field_name="signature_ts_key",
        source_kind="header_param",
        header_name="Stripe-Signature",
        header_param_name="t",
    )
    factory.endpoint_source(endpoint, field_name="idem_key", literal_value="idem-1")
    factory.endpoint_source(endpoint, field_name="event_key", literal_value="evt-1")
    factory.semantic_binding(endpoint, semantic_name="signature", value_key="signature_key")
    factory.semantic_binding(
        endpoint,
        semantic_name="signature_timestamp",
        value_key="signature_ts_key",
    )
    factory.semantic_binding(endpoint, semantic_name="idempotency_key", value_key="idem_key")
    factory.semantic_binding(endpoint, semantic_name="event_id", value_key="event_key")
    factory.signature_part(endpoint, source_kind="raw_body", sequence=10)
    factory.signature_part(endpoint, source_kind="literal", literal_value="suffix", sequence=20)
    endpoint.write(
        {
            "signature_verification_mode": "hmac",
            "signature_secret": HMAC_SECRET,
            "signature_timestamp_format": "unix",
            "signature_max_age_seconds": signature_max_age,
            "signature_max_future_skew_seconds": signature_max_skew,
        }
    )
    return endpoint


class TestEndpointDeliveryIdentityResolution(WebhookTestCase):
    """``_resolve_delivery_identity`` honors the configured policy."""

    def setUp(self):
        super().setUp()
        self.endpoint = _stripe_style_endpoint(self.factory)
        self.endpoint.delivery_identity_policy = "idempotency_key"

    def test_idempotency_policy_returns_resolved_idempotency_key(self):
        metadata = {"idempotency_key": "idem-1"}

        identity = self.endpoint._resolve_delivery_identity("body-sha", metadata)

        self.assertEqual(identity, ("idem-1", "idempotency_key"))

    def test_identity_unresolvable_under_explicit_policy_raises(self):
        with self.assertRaisesRegex(WebhookValidationError, "delivery identity"):
            self.endpoint._resolve_delivery_identity("body-sha", {})


class TestEndpointReplayIdentityResolution(WebhookTestCase):
    """``_resolve_replay_identity`` returns falsy under ``none`` policy and raises otherwise."""

    def setUp(self):
        super().setUp()
        self.endpoint = _stripe_style_endpoint(self.factory)
        self.endpoint.replay_identity_policy = "event_id"

    def test_event_id_policy_returns_resolved_event_id(self):
        metadata = {"event_id": "evt-1"}

        identity = self.endpoint._resolve_replay_identity(metadata)

        self.assertEqual(identity, ("evt-1", "event_id"))

    def test_none_policy_returns_falsy_pair(self):
        self.endpoint.replay_identity_policy = "none"

        self.assertEqual(self.endpoint._resolve_replay_identity({}), (False, False))

    def test_identity_unresolvable_under_explicit_policy_raises(self):
        with self.assertRaisesRegex(WebhookValidationError, "replay identity"):
            self.endpoint._resolve_replay_identity({})


class TestEndpointEndToEndSignatureVerification(WebhookTestCase):
    """A fresh, well-formed request verifies under a Stripe-style setup."""

    def test_fresh_request_with_correct_signature_verifies(self):
        endpoint = _stripe_style_endpoint(self.factory, signature_max_age=60, signature_max_skew=5)
        body = b'{"ok": true}'
        payload = {"ok": True}
        message = endpoint._build_signature_message(body, {}, payload)
        expected_signature = endpoint._compute_expected_signature(HMAC_SECRET, message)
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        headers = {"Stripe-Signature": f"t={timestamp}, v1={expected_signature}"}
        metadata = endpoint._extract_inbound_metadata(body, headers, payload)

        endpoint._verify_signature(body, headers, payload, metadata)


class TestSignaturePartResolveValueByKind(WebhookTestCase):
    """``_resolve_value`` returns the right slice of the request per ``source_kind``."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_header_param_part_returns_first_matching_parameter_value(self):
        part = self.factory.signature_part(
            self.endpoint,
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="v1",
        )

        value = part._resolve_value(
            self.endpoint,
            b"{}",
            {"Stripe-Signature": "t=1, v1=first, v1=second"},
            {},
        )

        self.assertEqual(value, "first")

    def test_header_param_part_with_no_matching_parameter_returns_falsy(self):
        part = self.factory.signature_part(
            self.endpoint,
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="v9",
        )

        value = part._resolve_value(self.endpoint, b"{}", {"Stripe-Signature": "t=1"}, {})

        self.assertFalse(value)


class TestSignaturePartWriteValidation(WebhookTestCase):
    """``write`` re-runs ``_check_part_configuration`` on the updated record."""

    def test_write_clearing_required_field_is_rejected(self):
        endpoint = self.factory.inbound_endpoint()
        part = self.factory.signature_part(
            endpoint,
            source_kind="header",
            header_name="X-Required",
        )

        with self.assertRaisesRegex(ValidationError, "header name"):
            part.write({"header_name": False})

    def test_write_unrelated_field_is_accepted(self):
        endpoint = self.factory.inbound_endpoint()
        part = self.factory.signature_part(
            endpoint,
            source_kind="header",
            header_name="X-Test",
        )

        part.write({"sequence": 99})

        self.assertEqual(part.sequence, 99)
