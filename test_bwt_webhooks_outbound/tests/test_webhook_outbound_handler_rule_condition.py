"""Behavioral tests for :class:`webhook.outbound.handler.rule.condition`.

Test suites in this module:

* :class:`TestOutboundConditionEvaluationOperators`
* :class:`TestOutboundConditionUnsupportedOperator`
"""

from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError
from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestOutboundConditionEvaluationOperators(WebhookTestCase):
    """``_outbound_condition_matches`` covers each supported operator."""

    def setUp(self):
        super().setUp()
        self.handler = self.factory.handler(direction="outbound")
        self.endpoint = self.factory.outbound_endpoint(handler=self.handler)
        self.delivery = self.factory.outbound_delivery(self.endpoint)
        self.request_dict = {
            "target_url": self.delivery.target_url,
            "http_method": "post",
            "headers": {},
            "payload": {"meta": {"ok": True}},
        }

    def _condition(self, **vals):
        rule = self.factory.outbound_rule(self.handler)
        return self.factory.outbound_rule_condition(rule, **vals)

    def test_equals_matches_when_actual_equals_expected(self):
        condition = self._condition(
            source_kind="request_field",
            source_expression="target_url",
            operator="equals",
            expected_value=self.delivery.target_url,
        )

        self.assertTrue(self.delivery._outbound_condition_matches(condition, {}, self.request_dict))

    def test_not_equals_matches_when_actual_differs_from_expected(self):
        condition = self._condition(
            source_kind="delivery_field",
            source_expression="state",
            operator="not_equals",
            expected_value="done",
        )

        self.assertTrue(self.delivery._outbound_condition_matches(condition, {}, self.request_dict))

    def test_contains_matches_substring_in_actual(self):
        condition = self._condition(
            source_kind="request_field",
            source_expression="target_url",
            operator="contains",
            expected_value="example.com",
        )

        self.assertTrue(self.delivery._outbound_condition_matches(condition, {}, self.request_dict))

    def test_is_set_matches_truthy_actual(self):
        condition = self._condition(
            source_kind="delivery_field",
            source_expression="state",
            operator="is_set",
        )

        self.assertTrue(self.delivery._outbound_condition_matches(condition, {}, self.request_dict))

    def test_not_set_matches_missing_actual(self):
        condition = self._condition(
            source_kind="request_field",
            source_expression="payload.missing",
            operator="not_set",
        )

        self.assertTrue(self.delivery._outbound_condition_matches(condition, {}, self.request_dict))

    def test_equals_does_not_match_when_actual_differs(self):
        condition = self._condition(
            source_kind="delivery_field",
            source_expression="state",
            operator="equals",
            expected_value="done",
        )

        self.assertFalse(self.delivery._outbound_condition_matches(condition, {}, self.request_dict))


class TestOutboundConditionUnsupportedOperator(WebhookTestCase):
    """An unsupported operator surfaces a configuration error."""

    def test_unsupported_operator_raises_configuration_error(self):
        from types import SimpleNamespace

        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)
        condition = SimpleNamespace(
            source_kind="delivery_field",
            source_expression="state",
            operator="unsupported",
            expected_value=False,
        )

        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "Unsupported outbound condition"):
            delivery._outbound_condition_matches(
                condition,
                {},
                {
                    "target_url": delivery.target_url,
                    "http_method": "post",
                    "headers": {},
                    "payload": {},
                },
            )
