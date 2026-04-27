"""Behavioral tests for :class:`webhook.outbound.endpoint.payload.rule`.

Test suites in this module:

* :class:`TestOutboundPayloadRuleConstraint`
* :class:`TestOutboundPayloadRuleEvaluation`
"""

from odoo.exceptions import ValidationError

from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestOutboundPayloadRuleConstraint(WebhookTestCase):
    """``_check_payload_rule_configuration`` enforces source key on non-literals."""

    def test_non_literal_source_kind_requires_source_expression(self):
        endpoint = self.factory.outbound_endpoint()

        with self.assertRaisesRegex(ValidationError, "Payload rules require Source Key"):
            self.factory.outbound_payload_rule(
                endpoint,
                target_path="meta.code",
                source_kind="context_key",
                source_expression=False,
            )


class TestOutboundPayloadRuleEvaluation(WebhookTestCase):
    """Payload rules drive payload construction inside ``_build_outbound_request``."""

    def test_literal_payload_rule_sets_target_path_value(self):
        endpoint = self.factory.outbound_endpoint()
        self.factory.outbound_payload_rule(
            endpoint,
            target_path="data.amount",
            source_kind="literal",
            literal_value="149.99",
        )
        delivery = self.factory.outbound_delivery(endpoint)

        request = delivery._build_outbound_request()

        self.assertEqual(request.payload["data"]["amount"], 149.99)

    def test_company_field_payload_rule_resolves_company_attribute(self):
        endpoint = self.factory.outbound_endpoint()
        self.factory.outbound_payload_rule(
            endpoint,
            target_path="meta.company",
            source_kind="company_field",
            source_expression="name",
        )
        delivery = self.factory.outbound_delivery(endpoint)

        request = delivery._build_outbound_request()

        self.assertEqual(request.payload["meta"]["company"], delivery.company_id.name)

    def test_context_key_payload_rule_uses_resolved_context_value(self):
        endpoint = self.factory.outbound_endpoint()
        self.factory.outbound_payload_rule(
            endpoint,
            target_path="data.customer",
            source_kind="context_key",
            source_expression="customer_name",
        )
        delivery = self.factory.outbound_delivery(endpoint)
        self.factory.outbound_context_line(delivery, key_name="customer_name", literal_value="Alice")

        request = delivery._build_outbound_request()

        self.assertEqual(request.payload["data"]["customer"], "Alice")

    def test_inactive_payload_rule_is_skipped(self):
        endpoint = self.factory.outbound_endpoint()
        self.factory.outbound_payload_rule(
            endpoint,
            target_path="data.skipped",
            source_kind="literal",
            literal_value="value",
            active=False,
        )
        delivery = self.factory.outbound_delivery(endpoint)

        request = delivery._build_outbound_request()

        self.assertNotIn("data", request.payload)
