from odoo import SUPERUSER_ID
from odoo.exceptions import ValidationError

from ..exceptions import (
    WebhookPayloadValidationError,
    WebhookProcessingConfigurationError,
    WebhookSignatureValidationError,
    WebhookValidationError,
)
from .common import WebhookEndpointTestCase


class TestWebhookEndpointCore(WebhookEndpointTestCase):
    def test_endpoint_route_count_action_and_handler(self):
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
