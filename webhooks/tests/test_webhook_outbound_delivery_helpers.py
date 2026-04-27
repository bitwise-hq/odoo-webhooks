from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from odoo import SUPERUSER_ID, fields
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.exceptions import ValidationError

from ..exceptions import WebhookProcessingConfigurationError
from ..models import webhook_outbound_delivery as outbound_delivery_model
from .common import WebhookRuleTestCase


class TestWebhookOutboundDeliveryHelpers(WebhookRuleTestCase):
    def _create_outbound_rule(self, handler, **values):
        create_vals = {
            "handler_id": handler.id,
            "name": values.pop("name", self._next_token("outbound_rule")),
            "result_status": values.pop("result_status", "send"),
        }
        create_vals.update(values)
        return self.env["webhook.handler.outbound.rule"].create(create_vals)

    def test_create_and_write_normalize_request_snapshots(self):
        endpoint = self._create_outbound_endpoint()
        snapshot_vals = self.env[
            "webhook.outbound.delivery"
        ]._prepare_endpoint_snapshot_vals(endpoint, {})

        self.assertEqual(snapshot_vals["execution_user_id"], self.env.user.id)
        self.assertEqual(snapshot_vals["request_headers_json"], "{}")
        self.assertEqual(snapshot_vals["payload_json"], "{}")
        self.assertTrue(snapshot_vals["name"].startswith(f"{endpoint.display_name} / "))

        delivery = self._create_outbound_delivery(
            endpoint,
            request_headers_json='{"X-Count": 7, "X-Enabled": true}',
            payload_json='{"amount": 12, "items": [1, 2]}',
        )

        self.assertEqual(delivery.execution_user_id, self.env.user)
        self.assertEqual(
            delivery._get_request_headers(),
            {"X-Count": "7", "X-Enabled": "True"},
        )
        self.assertEqual(delivery._get_payload(), {"amount": 12, "items": [1, 2]})

        delivery.write(
            {
                "request_headers_json": '{"X-Mode": "live", "X-Int": 9}',
                "payload_json": '{"nested": {"ok": true}}',
            }
        )

        self.assertEqual(
            delivery._get_request_headers(), {"X-Int": "9", "X-Mode": "live"}
        )
        self.assertEqual(delivery._get_payload(), {"nested": {"ok": True}})

        with self.assertRaisesRegex(ValidationError, "must be valid JSON"):
            self.env["webhook.outbound.delivery"].create(
                {
                    "endpoint_id": endpoint.id,
                    "request_headers_json": "{broken",
                }
            )
        with self.assertRaisesRegex(ValidationError, "must be a JSON object"):
            self.env["webhook.outbound.delivery"].create(
                {
                    "endpoint_id": endpoint.id,
                    "request_headers_json": "[]",
                }
            )
        with self.assertRaisesRegex(ValidationError, "must be valid JSON"):
            self.env["webhook.outbound.delivery"].create(
                {
                    "endpoint_id": endpoint.id,
                    "payload_json": "{broken",
                }
            )

    def test_helper_methods_cover_context_replay_and_payload_assignment(self):
        partner = self.env["res.partner"].create(
            {"name": "Webhook Partner", "is_company": True}
        )
        endpoint = self._create_outbound_endpoint(partner_id=partner.id)
        delivery = self._create_outbound_delivery(endpoint)
        self._create_outbound_context_line(
            delivery,
            key_name="trace_id",
            literal_value='"trace-001"',
        )
        self._create_outbound_context_line(
            delivery,
            key_name="endpoint_code",
            source_kind="endpoint_field",
            source_expression="code",
            sequence=20,
        )

        self.assertEqual(delivery._get_runtime_execution_user_id(), self.env.user.id)
        self.assertEqual(
            delivery.with_context(
                webhook_automated_execution=True
            )._get_runtime_execution_user_id(),
            SUPERUSER_ID,
        )
        self.assertEqual(
            delivery._get_queue_job_identity_key(),
            f"webhook_outbound_delivery_process:{delivery.id}",
        )
        self.assertEqual(
            delivery._get_queue_job_action_domain(),
            [
                (
                    "identity_key",
                    "=",
                    f"webhook_outbound_delivery_process:{delivery.id}",
                ),
                ("model_name", "=", "webhook.outbound.delivery"),
                ("method_name", "=", "process_delivery"),
            ],
        )
        action = delivery.action_view_queue_jobs()
        self.assertEqual(action["name"], "Outbound Queue Jobs")
        self.assertEqual(action["domain"], delivery._get_queue_job_action_domain())

        self.assertEqual(
            delivery._get_context_values(),
            {"trace_id": "trace-001", "endpoint_code": endpoint.code},
        )
        self.assertEqual(
            delivery._resolve_expression_value({"meta": {"code": 9}}, "meta.code"), 9
        )
        self.assertEqual(
            delivery._resolve_expression_value({"payload": [1, 2]}, "payload"),
            [1, 2],
        )
        self.assertEqual(
            delivery._resolve_source_value("endpoint_field", "code"),
            endpoint.code,
        )
        self.assertEqual(
            delivery._resolve_source_value("company_field", "name"),
            self.company.name,
        )
        self.assertEqual(
            delivery._resolve_source_value("partner_field", "name"),
            partner.name,
        )
        self.assertEqual(
            delivery._resolve_source_value(
                "request_field",
                "payload.meta.trace",
                request_data={"payload": {"meta": {"trace": "abc"}}},
            ),
            "abc",
        )
        self.assertFalse(delivery._resolve_source_value("request_field", False))
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "missing.attribute"
        ):
            delivery._resolve_source_value("endpoint_field", "missing.attribute")

        self.assertEqual(
            delivery._set_payload_path({}, "meta.trace", "abc"),
            {"meta": {"trace": "abc"}},
        )
        self.assertEqual(
            delivery._set_payload_path(False, "", {"ok": True}), {"ok": True}
        )
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "JSON object payload"
        ):
            delivery._set_payload_path([], "meta.trace", "abc")
        with self.assertRaisesRegex(
            WebhookProcessingConfigurationError, "collides with a non-object value"
        ):
            delivery._set_payload_path({"meta": "value"}, "meta.trace", "abc")

        first_attempt = delivery._create_attempt(
            {
                "http_method": "post",
                "target_url": delivery.target_url,
                "headers": {"X-Test": "1"},
                "payload": {"ok": True},
            }
        )
        second_attempt = delivery._create_attempt(
            {
                "http_method": "post",
                "target_url": delivery.target_url,
                "headers": {"X-Test": "2"},
                "payload": {"ok": False},
            },
            state="done",
            response_status_code=202,
            response_headers={"X-Reply": "yes"},
            response_body="accepted",
        )

        delivery.invalidate_recordset(["attempt_ids", "attempt_count"])
        delivery._compute_attempt_count()
        self.assertEqual(first_attempt.attempt_number, 1)
        self.assertFalse(first_attempt.finished_at)
        self.assertEqual(second_attempt.attempt_number, 2)
        self.assertTrue(second_attempt.finished_at)
        self.assertEqual(delivery.attempt_count, 2)

        replay_one = delivery.action_create_replay_delivery()
        replay_delivery = self.env["webhook.outbound.delivery"].browse(
            replay_one["res_id"]
        )
        replay_two = delivery.action_create_replay_delivery()
        second_replay = self.env["webhook.outbound.delivery"].browse(
            replay_two["res_id"]
        )
        delivery.invalidate_recordset(["replay_delivery_ids", "replay_count"])
        delivery._compute_replay_count()
        self.assertEqual(replay_delivery.replayed_from_delivery_id, delivery)
        self.assertEqual(second_replay.replayed_from_delivery_id, delivery)
        self.assertEqual(delivery.replay_count, 2)
        self.assertTrue(replay_delivery.name.endswith("Replay 1"))
        self.assertTrue(second_replay.name.endswith("Replay 2"))

        queued_replay = self._create_outbound_delivery(endpoint, state="queued")
        with self.assertRaisesRegex(ValidationError, "cannot be replayed"):
            queued_replay.action_create_replay_delivery()

    def test_queue_and_reset_delivery_state_helpers(self):
        archived_endpoint = self._create_outbound_endpoint(state="archived")
        archived_delivery = self._create_outbound_delivery(archived_endpoint)
        with self.assertRaisesRegex(ValidationError, "Archived outbound endpoint"):
            archived_delivery._queue_processing()

        endpoint = self._create_outbound_endpoint()
        delivery = self._create_outbound_delivery(endpoint, state="error")
        delayed = Mock()
        with patch.object(
            type(delivery), "with_user", autospec=True, return_value=delivery
        ) as with_user_mock:
            with patch.object(
                type(delivery), "with_delay", autospec=True, return_value=delayed
            ) as with_delay_mock:
                delivery._queue_processing()

        self.assertEqual(delivery.state, "queued")
        self.assertFalse(delivery.processing_error)
        self.assertTrue(delivery.queued_at)
        with_user_mock.assert_called()
        with_delay_mock.assert_called_once_with(
            delivery,
            identity_key=f"webhook_outbound_delivery_process:{delivery.id}",
        )
        delayed.process_delivery.assert_called_once_with()

        delivery.write(
            {
                "state": "error",
                "response_status_code": 500,
                "response_headers_json": '{"X-Test": "1"}',
                "response_body": "boom",
                "processing_note": "bad",
                "processing_error": "trace",
                "queued_at": fields.Datetime.now(),
                "processed_at": fields.Datetime.now(),
            }
        )
        delivery.action_reset_to_draft()
        self.assertEqual(delivery.state, "draft")
        self.assertFalse(delivery.queued_at)
        self.assertFalse(delivery.processed_at)
        self.assertFalse(delivery.processing_note)
        self.assertFalse(delivery.processing_error)
        self.assertFalse(delivery.response_status_code)
        self.assertFalse(delivery.response_headers_json)
        self.assertFalse(delivery.response_body)

        delivery.write({"state": "error"})
        delivery.action_cancel_delivery()
        self.assertEqual(delivery.state, "canceled")

    def test_apply_handler_result_and_condition_helpers(self):
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
