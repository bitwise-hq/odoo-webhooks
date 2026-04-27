"""Behavioral tests for :class:`webhook.outbound.delivery.context.line`.

Test suites in this module:

* :class:`TestOutboundContextLineConstraint`
* :class:`TestOutboundContextLineResolution`
"""

from odoo.exceptions import ValidationError

from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestOutboundContextLineConstraint(WebhookTestCase):
    """``_check_context_line_configuration`` enforces source key on non-literals."""

    def test_non_literal_source_kind_requires_source_expression(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)

        with self.assertRaisesRegex(ValidationError, "Context lines require Source Key"):
            self.factory.outbound_context_line(
                delivery,
                source_kind="endpoint_field",
                source_expression=False,
            )


class TestOutboundContextLineResolution(WebhookTestCase):
    """``_get_context_values`` resolves each line by its ``source_kind``."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.outbound_endpoint()
        self.delivery = self.factory.outbound_delivery(self.endpoint)

    def test_literal_context_line_decodes_quoted_value(self):
        self.factory.outbound_context_line(self.delivery, key_name="trace_id", literal_value='"trace-001"')

        values = self.delivery._get_context_values()

        self.assertEqual(values["trace_id"], "trace-001")

    def test_endpoint_field_context_line_resolves_endpoint_attribute(self):
        self.factory.outbound_context_line(
            self.delivery,
            key_name="endpoint_code",
            source_kind="endpoint_field",
            source_expression="code",
        )

        values = self.delivery._get_context_values()

        self.assertEqual(values["endpoint_code"], self.endpoint.code)

    def test_company_field_context_line_resolves_company_attribute(self):
        self.factory.outbound_context_line(
            self.delivery,
            key_name="company_name",
            source_kind="company_field",
            source_expression="name",
        )

        values = self.delivery._get_context_values()

        self.assertEqual(values["company_name"], self.delivery.company_id.name)

    def test_inactive_context_line_is_excluded(self):
        self.factory.outbound_context_line(
            self.delivery,
            key_name="hidden",
            literal_value='"v"',
            active=False,
        )

        values = self.delivery._get_context_values()

        self.assertNotIn("hidden", values)

    def test_context_lines_are_resolved_in_sequence_order(self):
        self.factory.outbound_context_line(
            self.delivery,
            key_name="trace_id",
            literal_value='"trace-001"',
            sequence=10,
        )
        self.factory.outbound_context_line(
            self.delivery,
            key_name="endpoint_code",
            source_kind="endpoint_field",
            source_expression="code",
            sequence=20,
        )

        values = self.delivery._get_context_values()

        self.assertEqual(list(values.keys()), ["trace_id", "endpoint_code"])
