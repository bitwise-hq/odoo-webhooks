from odoo import SUPERUSER_ID

from ..exceptions import WebhookProcessingConfigurationError
from .common import WebhookEndpointTestCase


class TestWebhookOutboundEndpointCore(WebhookEndpointTestCase):
    def test_target_normalization_counts_actions_and_partner_scope(self):
        endpoint_model = self.env["webhook.outbound.endpoint"]
        company_partner = self.company.partner_id
        child_partner = self.env["res.partner"].create(
            {
                "name": "Outbound Child Partner",
                "parent_id": company_partner.id,
                "type": "contact",
            }
        )

        self.assertEqual(endpoint_model._normalize_target_path(False), "/")
        self.assertEqual(
            endpoint_model._normalize_target_path("hooks/orders"), "/hooks/orders"
        )
        self.assertEqual(
            endpoint_model._normalize_target_path("?mode=live"), "/?mode=live"
        )
        self.assertEqual(
            endpoint_model._join_target_url(
                " https://api.example.com/ ",
                "hooks/orders",
            ),
            "https://api.example.com/hooks/orders",
        )
        self.assertFalse(endpoint_model._join_target_url("   ", "/hooks/orders"))
        self.assertEqual(
            endpoint_model._normalize_target_vals(
                {
                    "target_hostname": " https://api.example.com/ ",
                    "target_path": "hooks/orders",
                }
            ),
            {
                "target_hostname": "https://api.example.com",
                "target_path": "/hooks/orders",
            },
        )

        endpoint = self._create_outbound_endpoint(
            partner_id=child_partner.id,
            target_hostname=" https://api.example.com/ ",
            target_path="hooks/orders",
        )
        self._create_outbound_delivery(endpoint, state="done")
        self._create_outbound_delivery(endpoint, state="error")
        self._create_outbound_delivery(endpoint, state="dead_letter")

        endpoint._compute_target_url()
        endpoint._compute_related_counts()

        self.assertEqual(endpoint.target_hostname, "https://api.example.com")
        self.assertEqual(endpoint.target_path, "/hooks/orders")
        self.assertEqual(endpoint.target_url, "https://api.example.com/hooks/orders")
        self.assertEqual(endpoint.outbound_delivery_count, 3)
        self.assertEqual(endpoint.failed_delivery_count, 2)
        self.assertEqual(endpoint._get_scoped_partner(), company_partner)

        all_action = endpoint.action_view_outbound_deliveries()
        failed_action = endpoint.action_view_failed_outbound_deliveries()
        self.assertEqual(all_action["domain"], [("endpoint_id", "=", endpoint.id)])
        self.assertEqual(
            failed_action["domain"],
            [
                ("endpoint_id", "=", endpoint.id),
                ("state", "in", ("error", "dead_letter")),
            ],
        )
        self.assertEqual(all_action["context"], {"default_endpoint_id": endpoint.id})
        self.assertEqual(failed_action["context"], {"default_endpoint_id": endpoint.id})

        endpoint.write(
            {
                "target_hostname": " https://override.example.com/ ",
                "target_path": "?mode=live",
            }
        )
        self.assertEqual(endpoint.target_hostname, "https://override.example.com")
        self.assertEqual(endpoint.target_path, "/?mode=live")
        self.assertEqual(endpoint.target_url, "https://override.example.com/?mode=live")

    def test_execution_user_configuration_constraints(self):
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "Superuser cannot be used"
        ):
            self._create_outbound_endpoint(execution_user_id=SUPERUSER_ID)

        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "active internal user"
        ):
            self._create_outbound_endpoint(
                execution_user_id=self.env.ref("base.public_user").id
            )

        inactive_user = self._create_user(active=False)
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "active internal user"
        ):
            self._create_outbound_endpoint(execution_user_id=inactive_user.id)

        no_admin_user = self._create_user(
            group_ids=[(6, 0, [self.internal_user_group.id])]
        )
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "Webhook Administrator"
        ):
            self._create_outbound_endpoint(execution_user_id=no_admin_user.id)

        other_company = self.env["res.company"].create(
            {"name": self._next_token("company")}
        )
        other_company_user = self._create_user(
            company_id=other_company.id,
            company_ids=[(6, 0, [other_company.id])],
        )
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "outbound endpoint company"
        ):
            self._create_outbound_endpoint(execution_user_id=other_company_user.id)

    def test_outbound_configuration_constraints(self):
        invalid_cases = [
            (
                {
                    "target_hostname": "   ",
                },
                "target hostname",
            ),
            (
                {
                    "target_hostname": "example.com",
                },
                "URL scheme and hostname",
            ),
            (
                {
                    "target_hostname": "https://example.com?mode=live",
                },
                "cannot include query parameters",
            ),
            (
                {
                    "target_hostname": "https://example.com/path",
                },
                "Store the outbound request path separately",
            ),
            (
                {
                    "target_hostname": "https://example.com",
                    "target_path": "/hooks/orders#fragment",
                },
                "cannot include URL fragments",
            ),
            (
                {
                    "target_hostname": "https://example.com",
                    "timeout_seconds": 0,
                },
                "greater than zero seconds",
            ),
        ]

        for values, pattern in invalid_cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(
                    WebhookProcessingConfigurationError,
                    pattern,
                ):
                    self._create_outbound_endpoint(**values)
