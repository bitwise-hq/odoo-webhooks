import hashlib
from datetime import datetime, timedelta, timezone

from odoo import SUPERUSER_ID
from odoo.exceptions import ValidationError

from ..exceptions import (
    WebhookFreshnessValidationError,
    WebhookPayloadValidationError,
    WebhookProcessingConfigurationError,
    WebhookSignatureValidationError,
    WebhookValidationError,
)
from .common import WebhookRuleTestCase


class TestWebhookEndpointHelpers(WebhookRuleTestCase):
    def _create_user(self, **values):
        token = self._next_token("user")
        create_vals = {
            "name": values.pop("name", token),
            "login": values.pop("login", f"{token}@example.com"),
            "email": values.pop("email", f"{token}@example.com"),
            "company_id": values.pop("company_id", self.company.id),
            "company_ids": values.pop("company_ids", [(6, 0, [self.company.id])]),
            "group_ids": values.pop(
                "group_ids",
                [
                    (
                        6,
                        0,
                        [self.internal_user_group.id, self.webhook_admin_group.id],
                    )
                ],
            ),
            "active": values.pop("active", True),
        }
        create_vals.update(values)
        return (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(create_vals)
        )

    def _create_source(self, endpoint, **values):
        token = self._next_token("source")
        create_vals = {
            "endpoint_id": endpoint.id,
            "field_name": values.pop("field_name", token),
            "source_kind": values.pop("source_kind", "literal"),
            "literal_value": values.pop("literal_value", token),
        }
        create_vals.update(values)
        return self.env["webhook.endpoint.source"].create(create_vals)

    def _create_binding(self, endpoint, **values):
        create_vals = {
            "endpoint_id": endpoint.id,
            "semantic_name": values.pop("semantic_name", "topic"),
            "value_key": values.pop("value_key", self._next_token("binding")),
        }
        create_vals.update(values)
        return self.env["webhook.endpoint.semantic.binding"].create(create_vals)

    def _create_signature_part(self, endpoint, **values):
        token = self._next_token("signature_part")
        create_vals = {
            "endpoint_id": endpoint.id,
            "source_kind": values.pop("source_kind", "raw_body"),
            "literal_value": values.pop("literal_value", token),
        }
        create_vals.update(values)
        return self.env["webhook.endpoint.signature.part"].create(create_vals)

    def test_endpoint_route_count_action_and_handler_helpers(self):
        company_partner = self.company.partner_id
        child_partner = self.env["res.partner"].create(
            {
                "name": "Webhook Child Partner",
                "parent_id": company_partner.id,
                "type": "contact",
            }
        )
        default_handler = self._create_handler(
            direction="inbound", code="default-selector"
        )
        selected_handler = self._create_handler(
            direction="inbound", code="route-selector"
        )
        endpoint = self._create_inbound_endpoint(
            handler=default_handler,
            partner_id=child_partner.id,
            path=" helper-route ",
        )
        self._create_inbound_event(endpoint, state="done")
        self._create_inbound_event(endpoint, state="rejected")

        endpoint._compute_route_path()
        endpoint._compute_related_counts()

        self.assertEqual(endpoint.path, "helper-route")
        self.assertEqual(endpoint.route_path, "/webhooks/in/helper-route")
        self.assertEqual(endpoint.inbound_event_count, 1)
        self.assertEqual(endpoint.rejected_event_count, 1)
        self.assertEqual(endpoint._normalize_headers({"X-Test": "1"}), {"x-test": "1"})
        self.assertEqual(endpoint._extract_header_value({"X-Test": "1"}, "x-test"), "1")
        self.assertEqual(
            endpoint._extract_header_parameter_values(
                {"Stripe-Signature": 't=1, v1="abc", v1=def'},
                "Stripe-Signature",
                "v1",
            ),
            ["abc", "def"],
        )
        self.assertEqual(endpoint._normalize_partner(child_partner), company_partner)
        self.assertEqual(endpoint._get_scoped_partner(), company_partner)
        self.assertEqual(
            endpoint._resolve_handler({"handler_selector": "route-selector"}),
            selected_handler,
        )
        self.assertEqual(endpoint._resolve_handler({}), default_handler)

        inbound_action = endpoint.action_view_inbound_events()
        rejected_action = endpoint.action_view_rejected_events()
        self.assertEqual(
            inbound_action["domain"],
            [("endpoint_id", "=", endpoint.id), ("state", "!=", "rejected")],
        )
        self.assertEqual(
            rejected_action["domain"],
            [("endpoint_id", "=", endpoint.id), ("state", "=", "rejected")],
        )
        self.assertEqual(
            inbound_action["context"], {"default_endpoint_id": endpoint.id}
        )
        self.assertEqual(
            rejected_action["context"], {"default_endpoint_id": endpoint.id}
        )

    def test_endpoint_execution_user_configuration_constraints(self):
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "Superuser cannot be used"
        ):
            self._create_inbound_endpoint(execution_user_id=SUPERUSER_ID)

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "active internal user"
        ):
            self._create_inbound_endpoint(
                execution_user_id=self.env.ref("base.public_user").id
            )

        inactive_user = self._create_user(active=False)
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "active internal user"
        ):
            self._create_inbound_endpoint(execution_user_id=inactive_user.id)

        no_admin_user = self._create_user(
            group_ids=[(6, 0, [self.internal_user_group.id])]
        )
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "Webhook Administrator"
        ):
            self._create_inbound_endpoint(execution_user_id=no_admin_user.id)

        other_company = self.env["res.company"].create(
            {"name": self._next_token("company")}
        )
        other_company_user = self._create_user(
            company_id=other_company.id,
            company_ids=[(6, 0, [other_company.id])],
        )
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "endpoint company"
        ):
            self._create_inbound_endpoint(execution_user_id=other_company_user.id)

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

    def test_endpoint_validation_error_branches(self):
        with self.assertRaisesRegex(ValidationError, "without slashes"):
            self._create_inbound_endpoint(path="bad/path")
        with self.assertRaisesRegex(ValidationError, "cannot contain whitespace"):
            self._create_inbound_endpoint(path="bad path")

        archived_endpoint = self._create_inbound_endpoint(state="archived")
        with self.assertRaisesRegex(WebhookValidationError, "Archived endpoint"):
            archived_endpoint._validate_inbound_request(b"{}", {}, {}, {})

        payload_endpoint = self._create_inbound_endpoint(payload_contract="json_object")
        with self.assertRaisesRegex(
            WebhookPayloadValidationError, "top-level JSON object"
        ):
            payload_endpoint._validate_inbound_request(b"[]", {}, [], {})

        signature_endpoint = self._create_inbound_endpoint()
        self._create_source(
            signature_endpoint,
            field_name="signature_key",
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="v1",
        )
        self._create_binding(
            signature_endpoint,
            semantic_name="signature",
            value_key="signature_key",
        )
        self._create_signature_part(
            signature_endpoint,
            source_kind="raw_body",
            sequence=10,
        )
        signature_endpoint.write(
            {
                "signature_verification_mode": "hmac",
                "signature_secret": "topsecret",
                "signature_max_age_seconds": 0,
                "signature_max_future_skew_seconds": 0,
            }
        )

        with self.assertRaisesRegex(
            WebhookSignatureValidationError, "could not be resolved"
        ):
            signature_endpoint._verify_signature(b"{}", {}, {}, {})

        with self.assertRaisesRegex(
            WebhookSignatureValidationError, "could not be verified"
        ):
            signature_endpoint._verify_signature(
                b"{}",
                {"Stripe-Signature": "v1=wrong"},
                {},
                {},
            )

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

    def test_signature_verification_freshness_and_identity_helpers(self):
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
