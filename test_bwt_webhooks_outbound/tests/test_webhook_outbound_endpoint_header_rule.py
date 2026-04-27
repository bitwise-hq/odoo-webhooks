"""Behavioral tests for :class:`webhook.outbound.endpoint.header.rule`.

Test suites in this module:

* :class:`TestOutboundHeaderRuleConstraint`
* :class:`TestOutboundHeaderRuleEvaluation`
"""

from odoo.exceptions import ValidationError

from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestOutboundHeaderRuleConstraint(WebhookTestCase):
    """``_check_header_rule_configuration`` enforces source key on non-literals."""

    def test_non_literal_source_kind_requires_source_expression(self):
        endpoint = self.factory.outbound_endpoint()

        with self.assertRaisesRegex(ValidationError, "Header rules require Source Key"):
            self.factory.outbound_header_rule(endpoint, source_kind="context_key", source_expression=False)

    def test_literal_source_kind_does_not_require_source_expression(self):
        endpoint = self.factory.outbound_endpoint()

        rule = self.factory.outbound_header_rule(
            endpoint,
            header_name="X-Static",
            source_kind="literal",
            literal_value="value",
        )

        self.assertFalse(rule.source_expression)


class TestOutboundHeaderRuleEvaluation(WebhookTestCase):
    """Header rules apply to the request headers built by ``_build_outbound_request``."""

    def test_literal_header_rule_sets_static_header_value(self):
        endpoint = self.factory.outbound_endpoint()
        self.factory.outbound_header_rule(
            endpoint,
            header_name="X-Static",
            source_kind="literal",
            literal_value="static-source",
        )
        delivery = self.factory.outbound_delivery(endpoint)

        request = delivery._build_outbound_request()

        self.assertEqual(request.headers["X-Static"], "static-source")

    def test_context_key_header_rule_resolves_from_context_lines(self):
        endpoint = self.factory.outbound_endpoint()
        self.factory.outbound_header_rule(
            endpoint,
            header_name="X-Trace",
            source_kind="context_key",
            source_expression="trace_id",
        )
        delivery = self.factory.outbound_delivery(endpoint)
        self.factory.outbound_context_line(delivery, key_name="trace_id", literal_value="trace-001")

        request = delivery._build_outbound_request()

        self.assertEqual(request.headers["X-Trace"], "trace-001")

    def test_inactive_header_rule_is_skipped(self):
        endpoint = self.factory.outbound_endpoint()
        self.factory.outbound_header_rule(
            endpoint,
            header_name="X-Skipped",
            source_kind="literal",
            literal_value="value",
            active=False,
        )
        delivery = self.factory.outbound_delivery(endpoint)

        request = delivery._build_outbound_request()

        self.assertNotIn("X-Skipped", request.headers)

    def test_unresolved_header_value_becomes_empty_string(self):
        endpoint = self.factory.outbound_endpoint()
        self.factory.outbound_header_rule(
            endpoint,
            header_name="X-Empty",
            source_kind="context_key",
            source_expression="missing",
        )
        delivery = self.factory.outbound_delivery(endpoint)

        request = delivery._build_outbound_request()

        self.assertEqual(request.headers["X-Empty"], "")

    def test_header_rules_apply_in_sequence_order(self):
        endpoint = self.factory.outbound_endpoint()
        self.factory.outbound_header_rule(
            endpoint,
            header_name="X-Mode",
            source_kind="literal",
            literal_value="first",
            sequence=10,
        )
        self.factory.outbound_header_rule(
            endpoint,
            header_name="X-Mode",
            source_kind="literal",
            literal_value="second",
            sequence=20,
        )
        delivery = self.factory.outbound_delivery(endpoint)

        request = delivery._build_outbound_request()

        self.assertEqual(request.headers["X-Mode"], "second")
