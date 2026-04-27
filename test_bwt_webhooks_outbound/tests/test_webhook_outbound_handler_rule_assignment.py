"""Behavioral tests for :class:`webhook.outbound.handler.rule.assignment`.

Test suites in this module:

* :class:`TestOutboundAssignmentConfigurationConstraint`
* :class:`TestOutboundAssignmentApply`
"""

from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.services.value_objects import OutboundRequest
from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestOutboundAssignmentConfigurationConstraint(WebhookTestCase):
    """``_check_assignment_configuration`` enforces source key on non-literals."""

    def test_non_literal_source_kind_requires_source_expression(self):
        handler = self.factory.handler(direction="outbound")
        rule = self.factory.outbound_rule(handler)

        with self.assertRaisesRegex(ValidationError, "Outbound assignments require Source Key"):
            self.factory.outbound_rule_assignment(
                rule,
                target_scope="payload",
                target_expression="meta.count",
                source_kind="context_key",
                source_expression=False,
            )

    def test_literal_source_kind_does_not_require_source_expression(self):
        handler = self.factory.handler(direction="outbound")
        rule = self.factory.outbound_rule(handler)

        assignment = self.factory.outbound_rule_assignment(
            rule,
            target_scope="payload",
            target_expression="meta.count",
            source_kind="literal",
            literal_value="2",
        )

        self.assertFalse(assignment.source_expression)


class TestOutboundAssignmentApply(WebhookTestCase):
    """``_apply_assignment`` writes the value into the right scope of the request."""

    def setUp(self):
        super().setUp()
        self.delivery_model = self.env["bwt.webhook.outbound.delivery"]
        self.request = OutboundRequest(
            target_url="https://example.com/out",
            http_method="post",
            request_body_mode="json",
            headers={"X-Existing": "1"},
            payload={"meta": {"ok": True}},
            files={},
        )

    def _assignment(self, **vals):
        from types import SimpleNamespace

        return SimpleNamespace(**vals)

    def test_request_scope_overrides_top_level_attribute(self):
        assignment = self._assignment(target_scope="request", target_expression="target_url")

        self.delivery_model._apply_assignment(self.request, assignment, "https://override.example.com/x")

        self.assertEqual(self.request.target_url, "https://override.example.com/x")

    def test_header_scope_sets_header_to_string_value(self):
        assignment = self._assignment(target_scope="header", target_expression="X-Number")

        self.delivery_model._apply_assignment(self.request, assignment, 5)

        self.assertEqual(self.request.headers["X-Number"], "5")

    def test_header_scope_with_falsy_value_writes_empty_string(self):
        assignment = self._assignment(target_scope="header", target_expression="X-Empty")

        self.delivery_model._apply_assignment(self.request, assignment, False)

        self.assertEqual(self.request.headers["X-Empty"], "")

    def test_payload_scope_writes_dotted_path_into_payload(self):
        assignment = self._assignment(target_scope="payload", target_expression="meta.count")

        self.delivery_model._apply_assignment(self.request, assignment, 2)

        self.assertEqual(self.request.payload["meta"]["count"], 2)
