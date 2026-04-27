"""Behavioral tests for :class:`webhook.outbound.endpoint`.

Test suites in this module:

* :class:`TestOutboundEndpointTargetNormalization`
* :class:`TestOutboundEndpointTargetUrlCompute`
* :class:`TestOutboundEndpointConfigurationConstraints`
* :class:`TestOutboundEndpointRelatedCounts`
* :class:`TestOutboundEndpointDeliveryActions`
* :class:`TestOutboundEndpointStateActions`
"""

from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError
from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestOutboundEndpointTargetNormalization(WebhookTestCase):
    """``_normalize_target_path``, ``_join_target_url`` and ``_normalize_target_vals`` helpers."""

    def setUp(self):
        super().setUp()
        self.endpoint_model = self.env["bwt.webhook.outbound.endpoint"]

    def test_falsy_target_path_normalizes_to_root(self):
        self.assertEqual(self.endpoint_model._normalize_target_path(False), "/")

    def test_relative_target_path_gets_leading_slash(self):
        self.assertEqual(self.endpoint_model._normalize_target_path("hooks/orders"), "/hooks/orders")

    def test_query_only_target_path_is_prefixed_with_slash(self):
        self.assertEqual(self.endpoint_model._normalize_target_path("?mode=live"), "/?mode=live")

    def test_join_target_url_strips_hostname_whitespace_and_trailing_slash(self):
        self.assertEqual(
            self.endpoint_model._join_target_url(" https://api.example.com/ ", "hooks/orders"),
            "https://api.example.com/hooks/orders",
        )

    def test_blank_hostname_yields_falsy_join(self):
        self.assertFalse(self.endpoint_model._join_target_url("   ", "/hooks/orders"))

    def test_normalize_target_vals_strips_hostname_and_normalizes_path(self):
        normalized = self.endpoint_model._normalize_target_vals(
            {
                "target_hostname": " https://api.example.com/ ",
                "target_path": "hooks/orders",
            }
        )

        self.assertEqual(
            normalized,
            {
                "target_hostname": "https://api.example.com",
                "target_path": "/hooks/orders",
            },
        )


class TestOutboundEndpointTargetUrlCompute(WebhookTestCase):
    """``_compute_target_url`` and create/write normalization."""

    def test_create_normalizes_hostname_and_path_into_target_url(self):
        endpoint = self.factory.outbound_endpoint(
            target_hostname=" https://api.example.com/ ",
            target_path="hooks/orders",
        )

        self.assertEqual(endpoint.target_hostname, "https://api.example.com")
        self.assertEqual(endpoint.target_path, "/hooks/orders")
        self.assertEqual(endpoint.target_url, "https://api.example.com/hooks/orders")

    def test_write_renormalizes_hostname_and_path(self):
        endpoint = self.factory.outbound_endpoint()

        endpoint.write(
            {
                "target_hostname": " https://override.example.com/ ",
                "target_path": "?mode=live",
            }
        )

        self.assertEqual(endpoint.target_hostname, "https://override.example.com")
        self.assertEqual(endpoint.target_path, "/?mode=live")
        self.assertEqual(endpoint.target_url, "https://override.example.com/?mode=live")


class TestOutboundEndpointTargetUrlRendering(WebhookTestCase):
    """``_render_outbound_target_url`` substitutes ``{token}`` placeholders."""

    def test_render_substitutes_known_tokens_from_context(self):
        endpoint = self.factory.outbound_endpoint(
            target_hostname="https://api.example.com",
            target_path="/v1/customers/{customer_id}",
        )

        rendered = endpoint._render_outbound_target_url({"customer_id": "cus_42"})

        self.assertEqual(rendered, "https://api.example.com/v1/customers/cus_42")

    def test_render_raises_on_missing_token(self):
        endpoint = self.factory.outbound_endpoint(
            target_hostname="https://api.example.com",
            target_path="/v1/customers/{customer_id}",
        )

        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "customer_id"):
            endpoint._render_outbound_target_url({})

    def test_render_raises_on_falsy_token_value(self):
        endpoint = self.factory.outbound_endpoint(
            target_hostname="https://api.example.com",
            target_path="/v1/customers/{customer_id}",
        )

        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "customer_id"):
            endpoint._render_outbound_target_url({"customer_id": ""})

    def test_render_raises_when_hostname_resolves_to_empty(self):
        # Draft endpoints skip the hostname constraint so we can create one without a hostname.
        endpoint = self.factory.outbound_endpoint(state="draft", target_hostname=False)

        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "no resolvable target hostname"):
            endpoint._render_outbound_target_url({})


class TestOutboundEndpointConfigurationConstraints(WebhookTestCase):
    """``_check_outbound_configuration`` rejects malformed targets/timeouts."""

    def test_blank_hostname_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "target hostname"):
            self.factory.outbound_endpoint(target_hostname="   ")

    def test_hostname_without_scheme_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "URL scheme and hostname"):
            self.factory.outbound_endpoint(target_hostname="example.com")

    def test_hostname_with_query_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "cannot include query parameters"):
            self.factory.outbound_endpoint(target_hostname="https://example.com?mode=live")

    def test_hostname_with_path_is_rejected(self):
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError,
            "Store the outbound request path separately",
        ):
            self.factory.outbound_endpoint(target_hostname="https://example.com/path")

    def test_target_path_with_fragment_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "cannot include URL fragments"):
            self.factory.outbound_endpoint(
                target_hostname="https://example.com",
                target_path="/hooks/orders#fragment",
            )

    def test_zero_timeout_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "greater than zero seconds"):
            self.factory.outbound_endpoint(timeout_seconds=0)


class TestOutboundEndpointRelatedCounts(WebhookTestCase):
    """``_compute_related_counts`` totals all and failed deliveries."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.outbound_endpoint()

    def test_endpoint_with_no_deliveries_reports_zero_counts(self):
        self.endpoint._compute_related_counts()

        self.assertEqual(self.endpoint.outbound_delivery_count, 0)
        self.assertEqual(self.endpoint.failed_delivery_count, 0)

    def test_endpoint_counts_all_and_failed_deliveries_separately(self):
        self.factory.outbound_delivery(self.endpoint, state="done")
        self.factory.outbound_delivery(self.endpoint, state="error")
        self.factory.outbound_delivery(self.endpoint, state="dead_letter")

        self.endpoint._compute_related_counts()

        self.assertEqual(self.endpoint.outbound_delivery_count, 3)
        self.assertEqual(self.endpoint.failed_delivery_count, 2)


class TestOutboundEndpointDeliveryActions(WebhookTestCase):
    """``action_view_outbound_deliveries`` and ``action_view_failed_outbound_deliveries``."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.outbound_endpoint()

    def test_view_deliveries_action_filters_to_endpoint(self):
        action = self.endpoint.action_view_outbound_deliveries()

        self.assertEqual(action["domain"], [("endpoint_id", "=", self.endpoint.id)])
        self.assertEqual(action["context"], {"default_endpoint_id": self.endpoint.id})

    def test_view_failed_deliveries_action_restricts_to_failure_states(self):
        action = self.endpoint.action_view_failed_outbound_deliveries()

        self.assertEqual(
            action["domain"],
            [
                ("endpoint_id", "=", self.endpoint.id),
                ("state", "in", ("error", "dead_letter")),
            ],
        )


class TestOutboundEndpointStateActions(WebhookTestCase):
    """``action_activate``, ``action_set_draft`` and ``action_archive``."""

    def test_draft_endpoint_can_be_activated(self):
        endpoint = self.factory.outbound_endpoint(state="draft")

        endpoint.action_activate()

        self.assertEqual(endpoint.state, "active")

    def test_active_endpoint_can_be_moved_back_to_draft(self):
        endpoint = self.factory.outbound_endpoint(state="active")

        endpoint.action_set_draft()

        self.assertEqual(endpoint.state, "draft")

    def test_archived_endpoint_can_be_moved_back_to_draft(self):
        endpoint = self.factory.outbound_endpoint(state="archived")

        endpoint.action_set_draft()

        self.assertEqual(endpoint.state, "draft")

    def test_active_endpoint_can_be_archived(self):
        endpoint = self.factory.outbound_endpoint(state="active")

        endpoint.action_archive()

        self.assertEqual(endpoint.state, "archived")

    def test_active_endpoint_cannot_be_activated_again(self):
        endpoint = self.factory.outbound_endpoint(state="active")

        with self.assertRaisesRegex(ValidationError, "Only draft outbound endpoints"):
            endpoint.action_activate()

    def test_draft_endpoint_cannot_be_moved_to_draft(self):
        endpoint = self.factory.outbound_endpoint(state="draft")

        with self.assertRaisesRegex(ValidationError, "Only active or archived outbound endpoints"):
            endpoint.action_set_draft()

    def test_archived_endpoint_cannot_be_archived_again(self):
        endpoint = self.factory.outbound_endpoint(state="archived")

        with self.assertRaisesRegex(ValidationError, "Only draft or active outbound endpoints"):
            endpoint.action_archive()
