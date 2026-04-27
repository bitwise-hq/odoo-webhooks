"""Behavioral tests for :class:`webhook.outbound.handler.rule`.

Test suites in this module:

* :class:`TestOutboundRuleConfigurationConstraint`
* :class:`TestModelDrivenRuleEvaluation`
* :class:`TestModelDrivenRuleAssignmentBranches`
* :class:`TestHandlerExecuteOutbound`
* :class:`TestHandlerExecuteOutboundPythonCallback`
"""

from odoo.exceptions import ValidationError

from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestOutboundRuleConfigurationConstraint(WebhookTestCase):
    """``_check_outbound_rule_configuration`` validates retry delay sign."""

    def test_negative_retry_seconds_is_rejected(self):
        handler = self.factory.handler(direction="outbound")

        with self.assertRaisesRegex(ValidationError, "Retry delay must be zero"):
            self.factory.outbound_rule(handler, result_status="retry", retry_seconds=-1)

    def test_zero_retry_seconds_is_accepted(self):
        handler = self.factory.handler(direction="outbound")

        rule = self.factory.outbound_rule(handler, result_status="retry", retry_seconds=0)

        self.assertEqual(rule.retry_seconds, 0)


class TestModelDrivenRuleEvaluation(WebhookTestCase):
    """``_execute_model_driven_handler`` selects the first rule whose conditions match."""

    def setUp(self):
        super().setUp()
        self.handler = self.factory.handler(direction="outbound")
        self.endpoint = self.factory.outbound_endpoint(handler=self.handler)
        self.delivery = self.factory.outbound_delivery(self.endpoint)
        self.request_dict = {
            "target_url": self.delivery.target_url,
            "http_method": "post",
            "headers": {},
            "payload": {},
        }

    def test_no_rules_returns_default_send_status(self):
        result = self.delivery._execute_model_driven_handler(self.handler, request_data=self.request_dict)

        self.assertEqual(result, {"status": "send"})

    def test_rule_with_unmet_condition_does_not_match(self):
        rule = self.factory.outbound_rule(self.handler, result_status="cancel")
        self.factory.outbound_rule_condition(
            rule,
            source_kind="request_field",
            source_expression="target_url",
            operator="contains",
            expected_value="never-match",
        )

        result = self.delivery._execute_model_driven_handler(self.handler, request_data=self.request_dict)

        self.assertEqual(result, {"status": "send"})

    def test_matching_rule_returns_status_and_matched_rule_id(self):
        rule = self.factory.outbound_rule(self.handler, result_status="send")
        self.factory.outbound_rule_condition(
            rule,
            source_kind="request_field",
            source_expression="target_url",
            operator="equals",
            expected_value=self.delivery.target_url,
        )

        result = self.delivery._execute_model_driven_handler(self.handler, request_data=self.request_dict)

        self.assertEqual(result["status"], "send")
        self.assertEqual(result["matched_rule_id"], rule.id)

    def test_retry_rule_propagates_retry_seconds(self):
        rule = self.factory.outbound_rule(self.handler, result_status="retry", retry_seconds=25)
        self.factory.outbound_rule_condition(
            rule,
            source_kind="request_field",
            source_expression="target_url",
            operator="contains",
            expected_value="example.com",
        )

        result = self.delivery._execute_model_driven_handler(self.handler, request_data=self.request_dict)

        self.assertEqual(result["status"], "retry")
        self.assertEqual(result["seconds"], 25)

    def test_first_matching_rule_in_sequence_wins(self):
        first = self.factory.outbound_rule(self.handler, result_status="send", sequence=10)
        self.factory.outbound_rule_condition(
            first,
            source_kind="request_field",
            source_expression="target_url",
            operator="contains",
            expected_value="example.com",
        )
        second = self.factory.outbound_rule(self.handler, result_status="cancel", sequence=20)
        self.factory.outbound_rule_condition(
            second,
            source_kind="request_field",
            source_expression="target_url",
            operator="contains",
            expected_value="example.com",
        )

        result = self.delivery._execute_model_driven_handler(self.handler, request_data=self.request_dict)

        self.assertEqual(result["matched_rule_id"], first.id)

    def test_inactive_rule_is_skipped(self):
        active = self.factory.outbound_rule(self.handler, result_status="cancel", sequence=10, active=False)
        self.factory.outbound_rule_condition(
            active,
            source_kind="request_field",
            source_expression="target_url",
            operator="contains",
            expected_value="example.com",
        )

        result = self.delivery._execute_model_driven_handler(self.handler, request_data=self.request_dict)

        self.assertEqual(result, {"status": "send"})


class TestModelDrivenRuleAssignmentBranches(WebhookTestCase):
    """Assignments mutate the request across the request/header/payload scopes."""

    def setUp(self):
        super().setUp()
        self.handler = self.factory.handler(direction="outbound")
        self.endpoint = self.factory.outbound_endpoint(handler=self.handler)
        self.delivery = self.factory.outbound_delivery(self.endpoint)
        self.rule = self.factory.outbound_rule(self.handler, result_status="send")
        self.factory.outbound_rule_condition(
            self.rule,
            source_kind="request_field",
            source_expression="target_url",
            operator="contains",
            expected_value="example.com",
        )
        self.request_dict = {
            "target_url": self.delivery.target_url,
            "http_method": "post",
            "headers": {"X-Existing": "1"},
            "payload": {"meta": {"ok": True}},
        }

    def test_request_scope_assignment_overrides_target_url(self):
        self.factory.outbound_rule_assignment(
            self.rule,
            target_scope="request",
            target_expression="target_url",
            literal_value="https://override.example.com/out",
        )

        result = self.delivery._execute_model_driven_handler(self.handler, request_data=self.request_dict)

        self.assertEqual(result["target_url"], "https://override.example.com/out")

    def test_header_scope_assignment_adds_header(self):
        self.factory.outbound_rule_assignment(
            self.rule,
            target_scope="header",
            target_expression="X-Trace",
            literal_value="trace-001",
        )

        result = self.delivery._execute_model_driven_handler(self.handler, request_data=self.request_dict)

        self.assertEqual(result["headers"]["X-Trace"], "trace-001")

    def test_payload_scope_assignment_writes_target_path(self):
        self.factory.outbound_rule_assignment(
            self.rule,
            target_scope="payload",
            target_expression="meta.count",
            literal_value="2",
        )

        result = self.delivery._execute_model_driven_handler(self.handler, request_data=self.request_dict)

        self.assertEqual(result["payload"]["meta"]["count"], 2)

    def test_unchanged_request_keys_are_omitted_from_result(self):
        result = self.delivery._execute_model_driven_handler(self.handler, request_data=self.request_dict)

        self.assertNotIn("target_url", result)
        self.assertNotIn("headers", result)
        self.assertNotIn("payload", result)


class TestHandlerExecuteOutbound(WebhookTestCase):
    """``webhook.handler.execute_outbound`` enforces direction and dispatches."""

    def test_inbound_handler_cannot_process_outbound_delivery(self):
        handler = self.factory.handler(direction="inbound")
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)

        with self.assertRaisesRegex(ValidationError, "cannot process outbound"):
            handler.execute_outbound(delivery)

    def test_outbound_handler_dispatches_to_model_driven_engine(self):
        handler = self.factory.handler(direction="outbound")
        endpoint = self.factory.outbound_endpoint(handler=handler)
        delivery = self.factory.outbound_delivery(endpoint)

        result = handler.execute_outbound(
            delivery,
            request_data={
                "target_url": delivery.target_url,
                "http_method": "post",
                "headers": {},
                "payload": {},
            },
        )

        self.assertEqual(result, {"status": "send"})


class TestHandlerExecuteOutboundPythonCallback(WebhookTestCase):
    """``execute_outbound`` dispatches to a configured python callback."""

    def _install_callback(self, name, fn):
        partner_model = type(self.env["res.partner"])
        setattr(partner_model, name, fn)
        self.addCleanup(delattr, partner_model, name)

    def test_python_handler_invokes_configured_callback_and_returns_value(self):
        handler = self.factory.handler(
            direction="outbound",
            execution_mode="python",
            python_model_name="res.partner",
            python_method_name="webhook_outbound_callback_for_test",
        )
        endpoint = self.factory.outbound_endpoint(handler=handler)
        delivery = self.factory.outbound_delivery(endpoint)
        captured = {}

        def callback(self_model, dlv):
            captured["delivery_id"] = dlv.id
            return {"status": "send", "called": True}

        self._install_callback("webhook_outbound_callback_for_test", callback)

        result = handler.execute_outbound(delivery)

        self.assertEqual(result, {"status": "send", "called": True})
        self.assertEqual(captured["delivery_id"], delivery.id)

    def test_python_handler_with_missing_callback_method_is_rejected(self):
        handler = self.factory.handler(
            direction="outbound",
            execution_mode="python",
            python_model_name="res.partner",
            python_method_name="webhook_outbound_missing_method",
        )
        endpoint = self.factory.outbound_endpoint(handler=handler)
        delivery = self.factory.outbound_delivery(endpoint)

        with self.assertRaisesRegex(ValidationError, "could not be found"):
            handler.execute_outbound(delivery)
