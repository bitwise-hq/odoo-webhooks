from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from odoo.addons.queue_job.exception import RetryableJobError

from ..exceptions import WebhookProcessingConfigurationError
from ..models import webhook_outbound_delivery as outbound_delivery_model
from .common import WebhookOutboundDeliveryTestCase


class TestWebhookOutboundDeliveryProcessing(WebhookOutboundDeliveryTestCase):
    def test_model_driven_handler_rule_evaluation_branches(self):
        handler = self._create_handler(direction="outbound")
        endpoint = self._create_outbound_endpoint(handler=handler)
        delivery = self._create_outbound_delivery(endpoint)
        self._create_outbound_context_line(
            delivery,
            key_name="trace_id",
            literal_value='"trace-001"',
        )
        request_data = {
            "target_url": delivery.target_url,
            "http_method": "post",
            "headers": {"X-Test": "1"},
            "payload": {"meta": {"ok": True}},
        }

        no_match_rule = self._create_outbound_rule(handler, result_status="send")
        self.env["webhook.handler.outbound.rule.condition"].create(
            {
                "rule_id": no_match_rule.id,
                "source_kind": "request_field",
                "source_expression": "target_url",
                "operator": "contains",
                "expected_value": "does-not-match",
            }
        )

        self.assertEqual(
            delivery._execute_model_driven_handler(handler, request_data=request_data),
            {"status": "send"},
        )

        matched_send_rule = self._create_outbound_rule(
            handler,
            sequence=20,
            result_status="send",
        )
        self.env["webhook.handler.outbound.rule.condition"].create(
            {
                "rule_id": matched_send_rule.id,
                "source_kind": "request_field",
                "source_expression": "target_url",
                "operator": "equals",
                "expected_value": delivery.target_url,
            }
        )

        send_result = delivery._execute_model_driven_handler(
            handler, request_data=request_data
        )

        self.assertEqual(send_result["status"], "send")
        self.assertEqual(send_result["matched_rule_id"], matched_send_rule.id)
        self.assertNotIn("target_url", send_result)
        self.assertNotIn("http_method", send_result)
        self.assertNotIn("headers", send_result)
        self.assertNotIn("payload", send_result)

        matched_send_rule.write({"active": False})
        retry_rule = self._create_outbound_rule(
            handler,
            sequence=30,
            result_status="retry",
            retry_seconds=25,
            note="Retry later",
        )
        self.env["webhook.handler.outbound.rule.condition"].create(
            {
                "rule_id": retry_rule.id,
                "source_kind": "request_field",
                "source_expression": "target_url",
                "operator": "contains",
                "expected_value": "example.com",
            }
        )
        self.env["webhook.handler.outbound.assignment"].create(
            {
                "rule_id": retry_rule.id,
                "target_scope": "request",
                "target_expression": "target_url",
                "source_kind": "literal",
                "literal_value": "https://override.example.com/out",
            }
        )
        self.env["webhook.handler.outbound.assignment"].create(
            {
                "rule_id": retry_rule.id,
                "target_scope": "request",
                "target_expression": "http_method",
                "source_kind": "literal",
                "literal_value": "patch",
            }
        )
        self.env["webhook.handler.outbound.assignment"].create(
            {
                "rule_id": retry_rule.id,
                "target_scope": "header",
                "target_expression": "X-Trace",
                "source_kind": "context_key",
                "source_expression": "trace_id",
            }
        )
        self.env["webhook.handler.outbound.assignment"].create(
            {
                "rule_id": retry_rule.id,
                "target_scope": "payload",
                "target_expression": "meta.count",
                "source_kind": "literal",
                "literal_value": "2",
            }
        )

        retry_result = delivery._execute_model_driven_handler(
            handler, request_data=request_data
        )

        self.assertEqual(retry_result["status"], "retry")
        self.assertEqual(retry_result["matched_rule_id"], retry_rule.id)
        self.assertEqual(retry_result["seconds"], 25)
        self.assertEqual(retry_result["target_url"], "https://override.example.com/out")
        self.assertEqual(retry_result["http_method"], "patch")
        self.assertEqual(
            retry_result["headers"], {"X-Test": "1", "X-Trace": "trace-001"}
        )
        self.assertEqual(retry_result["payload"], {"meta": {"ok": True, "count": 2}})

    def test_apply_handler_result_and_condition_matching(self):
        endpoint = self._create_outbound_endpoint()
        delivery = self._create_outbound_delivery(endpoint)
        request_data = {
            "target_url": delivery.target_url,
            "http_method": "post",
            "headers": {"X-Test": "1"},
            "payload": {"meta": {"ok": True}},
        }

        unchanged_result, unchanged_request = delivery._apply_handler_result(
            True, request_data
        )
        self.assertTrue(unchanged_result)
        self.assertEqual(unchanged_request, request_data)

        result, updated_request = delivery._apply_handler_result(
            {
                "status": "send",
                "target_url": "https://override.example.com/out",
                "http_method": "PATCH",
                "headers": {"X-Number": 5},
                "payload": {"meta": {"count": 2}},
            },
            request_data,
        )
        self.assertEqual(result["status"], "send")
        self.assertEqual(
            updated_request["target_url"], "https://override.example.com/out"
        )
        self.assertEqual(updated_request["http_method"], "patch")
        self.assertEqual(updated_request["headers"], {"X-Number": "5"})
        self.assertEqual(updated_request["payload"], {"meta": {"count": 2}})

        set_condition = SimpleNamespace(
            source_kind="delivery_field",
            source_expression="state",
            operator="is_set",
            expected_value=False,
        )
        not_set_condition = SimpleNamespace(
            source_kind="request_field",
            source_expression="payload.missing",
            operator="not_set",
            expected_value=False,
        )
        equals_condition = SimpleNamespace(
            source_kind="request_field",
            source_expression="target_url",
            operator="equals",
            expected_value=delivery.target_url,
        )
        not_equals_condition = SimpleNamespace(
            source_kind="delivery_field",
            source_expression="state",
            operator="not_equals",
            expected_value="done",
        )
        contains_condition = SimpleNamespace(
            source_kind="request_field",
            source_expression="target_url",
            operator="contains",
            expected_value="example.com",
        )
        invalid_condition = SimpleNamespace(
            source_kind="delivery_field",
            source_expression="state",
            operator="unsupported",
            expected_value=False,
        )

        self.assertTrue(
            delivery._outbound_condition_matches(set_condition, {}, request_data)
        )
        self.assertTrue(
            delivery._outbound_condition_matches(not_set_condition, {}, request_data)
        )
        self.assertTrue(
            delivery._outbound_condition_matches(equals_condition, {}, request_data)
        )
        self.assertTrue(
            delivery._outbound_condition_matches(not_equals_condition, {}, request_data)
        )
        self.assertTrue(
            delivery._outbound_condition_matches(contains_condition, {}, request_data)
        )
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "Unsupported outbound condition"
        ):
            delivery._outbound_condition_matches(invalid_condition, {}, request_data)

    def test_process_delivery_transport_and_handler_branches(self):
        endpoint = self._create_outbound_endpoint()

        success_delivery = self._create_outbound_delivery(endpoint)
        with patch.object(
            outbound_delivery_model.requests,
            "request",
            return_value=Mock(
                status_code=202, headers={"X-Reply": "yes"}, text="accepted"
            ),
        ) as request_mock:
            success_delivery.process_delivery()
        self.assertEqual(success_delivery.state, "done")
        self.assertEqual(success_delivery.response_status_code, 202)
        self.assertEqual(success_delivery.attempt_ids[:1].state, "done")
        request_mock.assert_called_once()

        dead_letter_delivery = self._create_outbound_delivery(endpoint)
        with patch.object(
            outbound_delivery_model.requests,
            "request",
            return_value=Mock(
                status_code=422, headers={"X-Reply": "no"}, text="invalid"
            ),
        ):
            dead_letter_delivery.process_delivery()
        self.assertEqual(dead_letter_delivery.state, "dead_letter")
        self.assertIn("HTTP 422", dead_letter_delivery.processing_error)
        self.assertEqual(dead_letter_delivery.attempt_ids[:1].state, "dead_letter")

        retry_delivery = self._create_outbound_delivery(endpoint)
        with patch.object(
            outbound_delivery_model.requests,
            "request",
            return_value=Mock(
                status_code=503, headers={"Retry-After": "5"}, text="busy"
            ),
        ):
            with self.assertRaisesRegex(RetryableJobError, "HTTP 503"):
                retry_delivery.process_delivery()
        self.assertEqual(retry_delivery.state, "error")
        self.assertEqual(retry_delivery.attempt_ids[:1].state, "error")

        request_error_delivery = self._create_outbound_delivery(endpoint)
        with patch.object(
            outbound_delivery_model.requests,
            "request",
            side_effect=requests.RequestException("network down"),
        ):
            with self.assertRaisesRegex(RetryableJobError, "network down"):
                request_error_delivery.process_delivery()
        self.assertEqual(request_error_delivery.state, "error")
        self.assertEqual(request_error_delivery.attempt_ids[:1].state, "error")
        self.assertIn("network down", request_error_delivery.processing_error)

        cancel_handler = self._create_handler(direction="outbound")
        cancel_delivery = self._create_outbound_delivery(
            self._create_outbound_endpoint(handler=cancel_handler)
        )
        with patch.object(
            type(cancel_handler),
            "execute_outbound",
            autospec=True,
            return_value={"status": "cancel", "note": "Canceled by handler"},
        ):
            with patch.object(
                outbound_delivery_model.requests, "request"
            ) as request_mock:
                cancel_delivery.process_delivery()
        self.assertEqual(cancel_delivery.state, "canceled")
        self.assertEqual(cancel_delivery.attempt_ids[:1].state, "canceled")
        request_mock.assert_not_called()

        dead_letter_handler = self._create_handler(direction="outbound")
        dead_letter_delivery = self._create_outbound_delivery(
            self._create_outbound_endpoint(handler=dead_letter_handler)
        )
        with patch.object(
            type(dead_letter_handler),
            "execute_outbound",
            autospec=True,
            return_value={"status": "dead_letter", "note": "Blocked by handler"},
        ):
            with patch.object(
                outbound_delivery_model.requests, "request"
            ) as request_mock:
                dead_letter_delivery.process_delivery()
        self.assertEqual(dead_letter_delivery.state, "dead_letter")
        self.assertEqual(dead_letter_delivery.attempt_ids[:1].state, "dead_letter")
        self.assertEqual(dead_letter_delivery.processing_note, "Blocked by handler")
        request_mock.assert_not_called()

        retry_handler = self._create_handler(direction="outbound")
        retry_delivery = self._create_outbound_delivery(
            self._create_outbound_endpoint(handler=retry_handler)
        )
        with patch.object(
            type(retry_handler),
            "execute_outbound",
            autospec=True,
            return_value={
                "status": "retry",
                "note": "Retry by handler",
                "seconds": 12,
            },
        ):
            with patch.object(
                outbound_delivery_model.requests, "request"
            ) as request_mock:
                with self.assertRaisesRegex(RetryableJobError, "Retry by handler"):
                    retry_delivery.process_delivery()
        self.assertEqual(retry_delivery.state, "error")
        self.assertEqual(retry_delivery.attempt_ids[:1].state, "error")
        self.assertEqual(retry_delivery.processing_note, "Retry by handler")
        request_mock.assert_not_called()

        false_handler = self._create_handler(direction="outbound")
        false_delivery = self._create_outbound_delivery(
            self._create_outbound_endpoint(handler=false_handler)
        )
        with patch.object(
            type(false_handler),
            "execute_outbound",
            autospec=True,
            return_value=False,
        ):
            with patch.object(
                outbound_delivery_model.requests, "request"
            ) as request_mock:
                false_delivery.process_delivery()
        self.assertEqual(false_delivery.state, "canceled")
        self.assertEqual(false_delivery.attempt_ids[:1].state, "canceled")
        request_mock.assert_not_called()

        dead_handler = self._create_handler(direction="outbound")
        dead_handler_delivery = self._create_outbound_delivery(
            self._create_outbound_endpoint(handler=dead_handler)
        )
        with patch.object(
            type(dead_handler),
            "execute_outbound",
            autospec=True,
            return_value={"status": "dead_letter", "note": "Dead by handler"},
        ):
            with patch.object(
                outbound_delivery_model.requests, "request"
            ) as request_mock:
                dead_handler_delivery.process_delivery()
        self.assertEqual(dead_handler_delivery.state, "dead_letter")
        self.assertEqual(dead_handler_delivery.attempt_ids[:1].state, "dead_letter")
        request_mock.assert_not_called()

        false_handler = self._create_handler(direction="outbound")
        false_delivery = self._create_outbound_delivery(
            self._create_outbound_endpoint(handler=false_handler)
        )
        with patch.object(
            type(false_handler), "execute_outbound", autospec=True, return_value=False
        ):
            with patch.object(
                outbound_delivery_model.requests, "request"
            ) as request_mock:
                false_delivery.process_delivery()
        self.assertEqual(false_delivery.state, "canceled")
        self.assertEqual(false_delivery.attempt_ids[:1].state, "canceled")
        request_mock.assert_not_called()
