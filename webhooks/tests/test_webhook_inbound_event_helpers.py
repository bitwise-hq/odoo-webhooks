import hashlib
import json
from unittest.mock import Mock, patch

from odoo import SUPERUSER_ID, fields
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.exceptions import ValidationError

from ..exceptions import WebhookPayloadValidationError
from .common import WebhookRuleTestCase


class TestWebhookInboundEventHelpers(WebhookRuleTestCase):
    def _create_source(self, endpoint, **values):
        token = self._next_token("source")
        create_vals = {
            "endpoint_id": endpoint.id,
            "field_name": values.pop("field_name", token),
            "source_kind": values.pop("source_kind", "literal"),
            "literal_value": values.pop("literal_value", token),
        }
        create_vals.update(values)
        return self.env["webhook.endpoint.source"].create(create_vals)

    def _create_binding(self, endpoint, **values):
        create_vals = {
            "endpoint_id": endpoint.id,
            "semantic_name": values.pop("semantic_name", "topic"),
            "value_key": values.pop("value_key", self._next_token("binding")),
        }
        create_vals.update(values)
        return self.env["webhook.endpoint.semantic.binding"].create(create_vals)

    def _create_inbound_rule(self, handler, **values):
        create_vals = {
            "handler_id": handler.id,
            "name": values.pop("name", self._next_token("inbound_rule")),
            "action_type": values.pop("action_type", "done"),
        }
        create_vals.update(values)
        return self.env["webhook.handler.inbound.rule"].create(create_vals)

    def test_payload_resolution_and_lookup_helpers(self):
        endpoint = self._create_inbound_endpoint()
        event_model = self.env["webhook.inbound.event"]
        event = self._create_inbound_event(
            endpoint,
            topic="partner.sync",
            delivery_id="DEL-1",
            resolved_values={
                "customer_name": "Alice Example",
                "external_ref": "EXT-1",
            },
        )

        self.assertEqual(event_model._parse_payload(""), {})
        self.assertFalse(event_model._parse_payload("{broken json"))
        with self.assertRaisesRegex(WebhookPayloadValidationError, "valid JSON"):
            event_model._parse_payload("{broken json", raise_on_invalid=True)

        event.write({"resolved_values_json": "{broken json"})
        self.assertEqual(event.get_resolved_values(), {})
        self.assertEqual(
            event.get_resolved_value("customer_name", "fallback"), "fallback"
        )

        event.write(
            {
                "resolved_values_json": self._serialize(
                    {
                        "customer_name": "Alice Example",
                        "external_ref": "EXT-1",
                    }
                )
            }
        )
        self.assertEqual(event.get_resolved_value("customer_name"), "Alice Example")
        self.assertEqual(event._decode_literal_value('{"flag": true}'), {"flag": True})
        self.assertEqual(event._decode_literal_value("plain text"), "plain text")
        self.assertEqual(
            event._resolve_inbound_source_value("literal", literal_value="42"),
            42,
        )
        self.assertEqual(
            event._resolve_inbound_source_value("resolved_value", "customer_name"),
            "Alice Example",
        )
        self.assertEqual(
            event._resolve_inbound_source_value("semantic_field", "topic"),
            "partner.sync",
        )
        self.assertEqual(
            event._resolve_inbound_source_value("event_field", "delivery_id"),
            "DEL-1",
        )
        self.assertEqual(event_model._get_runtime_execution_user_id(), self.env.user.id)
        self.assertEqual(
            event_model.with_context(
                webhook_automated_execution=True
            )._get_runtime_execution_user_id(),
            SUPERUSER_ID,
        )

        handler = self._create_handler(direction="inbound")
        rule = self._create_inbound_rule(handler, action_type="done")
        condition = self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "semantic_field",
                "source_expression": "topic",
                "operator": "contains",
                "expected_value": "partner",
            }
        )
        self.assertTrue(event._inbound_condition_matches(condition))

        self.env["webhook.handler.inbound.rule.lookup"].create(
            {
                "rule_id": rule.id,
                "target_field_name": "ref",
                "source_kind": "resolved_value",
                "source_expression": "external_ref",
            }
        )
        self.env["webhook.handler.inbound.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "resolved_value",
                "source_expression": "customer_name",
            }
        )
        self.env["webhook.handler.inbound.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "context_key",
                "target_expression": "payload",
                "source_kind": "literal",
                "literal_value": '{"flag": true}',
            }
        )

        self.assertEqual(
            event._build_inbound_lookup_domain(rule), [("ref", "=", "EXT-1")]
        )
        self.assertEqual(
            event._build_inbound_assignment_values(rule, target_kind="field"),
            {"name": "Alice Example"},
        )
        self.assertEqual(
            event._build_inbound_assignment_values(rule, target_kind="context_key"),
            {"payload": {"flag": True}},
        )

    def test_receive_webhook_request_creates_replay_and_reuses_duplicate_delivery(self):
        endpoint = self._create_inbound_endpoint()
        self._create_source(
            endpoint,
            field_name="delivery_key",
            source_kind="header",
            header_name="X-Delivery-Id",
        )
        self._create_source(
            endpoint,
            field_name="event_key",
            source_kind="header",
            header_name="X-Event-Id",
        )
        self._create_binding(
            endpoint,
            semantic_name="delivery_id",
            value_key="delivery_key",
        )
        self._create_binding(
            endpoint,
            semantic_name="event_id",
            value_key="event_key",
        )
        endpoint.write(
            {
                "delivery_identity_policy": "delivery_id",
                "replay_identity_policy": "event_id",
            }
        )

        first = self.env["webhook.inbound.event"]._receive_webhook_request(
            endpoint,
            b"{}",
            {"X-Delivery-Id": "delivery-1", "X-Event-Id": "event-1"},
        )
        second = self.env["webhook.inbound.event"]._receive_webhook_request(
            endpoint,
            b"{}",
            {"X-Delivery-Id": "delivery-2", "X-Event-Id": "event-1"},
        )
        duplicate = self.env["webhook.inbound.event"]._receive_webhook_request(
            endpoint,
            b"{}",
            {"X-Delivery-Id": "delivery-1", "X-Event-Id": "event-1"},
        )

        self.assertEqual(first.delivery_identity_key, "delivery-1")
        self.assertEqual(first.delivery_kind, "primary")
        self.assertEqual(second.delivery_identity_key, "delivery-2")
        self.assertEqual(second.delivery_kind, "replay")
        self.assertEqual(second.replayed_from_event_id, first)
        self.assertEqual(duplicate, first)
        self.assertEqual(
            self.env["webhook.inbound.event"].search_count(
                [("endpoint_id", "=", endpoint.id)]
            ),
            2,
        )
        self.assertEqual(
            first.queue_job_identity_key, f"webhook_inbound_event_process:{first.id}"
        )
        self.assertEqual(
            first._get_queue_job_action_domain(),
            [
                ("identity_key", "=", f"webhook_inbound_event_process:{first.id}"),
                ("model_name", "=", "webhook.inbound.event"),
                ("method_name", "=", "process_event"),
            ],
        )
        action = first.action_view_queue_jobs()
        self.assertEqual(action["name"], "Inbound Queue Jobs")
        self.assertEqual(action["domain"], first._get_queue_job_action_domain())

    def test_receive_webhook_request_logs_rejected_invalid_payload(self):
        endpoint = self._create_inbound_endpoint()
        body = b"{broken json"
        headers = {"X-Request-Id": "req-1"}

        with self.assertRaisesRegex(WebhookPayloadValidationError, "valid JSON"):
            self.env["webhook.inbound.event"]._receive_webhook_request(
                endpoint, body, headers
            )

        rejected = self.env["webhook.inbound.event"].search(
            [("endpoint_id", "=", endpoint.id), ("state", "=", "rejected")],
            order="id desc",
            limit=1,
        )

        self.assertTrue(rejected)
        self.assertEqual(rejected.rejection_category, "payload")
        self.assertIn("valid JSON", rejected.rejection_reason)
        self.assertEqual(json.loads(rejected.payload_json), {})
        self.assertEqual(rejected.body_sha256, hashlib.sha256(body).hexdigest())

    def test_rejection_logging_and_queue_observability_helpers(self):
        endpoint = self._create_inbound_endpoint()
        event_model = self.env["webhook.inbound.event"]
        event = self._create_inbound_event(endpoint)

        event._compute_queue_job_identity_key()
        event._compute_queue_job_observability()

        self.assertEqual(
            event.queue_job_identity_key, f"webhook_inbound_event_process:{event.id}"
        )
        self.assertFalse(event.queue_job_ids)
        self.assertEqual(event.queue_job_count, 0)
        self.assertFalse(event.latest_queue_job_id)
        self.assertFalse(event.latest_queue_job_state)

        with patch.object(
            type(endpoint),
            "_resolve_delivery_identity",
            autospec=True,
            side_effect=ValidationError("delivery identity missing"),
        ):
            with patch.object(
                type(endpoint),
                "_resolve_replay_identity",
                autospec=True,
                side_effect=ValidationError("replay identity missing"),
            ):
                rejected = event_model._log_rejected_request(
                    endpoint,
                    b"{broken json",
                    {"X-Test": "1"},
                    payload_parse_failed=True,
                    rejection_category="payload",
                    rejection_reason="parse failed",
                )

        self.assertEqual(rejected.state, "rejected")
        self.assertEqual(rejected.rejection_reason, "parse failed")
        self.assertEqual(json.loads(rejected.request_headers_json), {"X-Test": "1"})
        self.assertEqual(json.loads(rejected.payload_json), {})
        self.assertFalse(rejected.delivery_identity_key)
        self.assertFalse(rejected.replay_identity_key)

        with patch.object(
            type(event_model),
            "create",
            autospec=True,
            side_effect=lambda model, values: values,
        ):
            endpointless_vals = event_model._log_rejected_request(
                False,
                b'{"ok": true}',
                {"X-Other": "2"},
                payload={"ok": True},
                rejection_category="manual",
                rejection_reason="blocked",
            )

        self.assertFalse(endpointless_vals["endpoint_id"])
        self.assertEqual(endpointless_vals["company_id"], self.env.company.id)
        self.assertEqual(json.loads(endpointless_vals["payload_json"]), {"ok": True})
        self.assertEqual(
            json.loads(endpointless_vals["request_headers_json"]),
            {"X-Other": "2"},
        )

    def test_queue_processing_reset_and_condition_helper_branches(self):
        endpoint = self._create_inbound_endpoint()
        queue_event = self._create_inbound_event(
            endpoint,
            execution_user_id=self.env.user.id,
            processing_error="stale error",
        )
        delayed = Mock()

        with patch.object(
            type(queue_event), "with_user", autospec=True, return_value=queue_event
        ) as with_user_mock:
            with patch.object(
                type(queue_event), "with_delay", autospec=True, return_value=delayed
            ) as with_delay_mock:
                self.assertTrue(queue_event.action_queue_processing())

        self.assertEqual(queue_event.execution_user_id, self.env.user)
        self.assertFalse(queue_event.processing_error)
        with_user_mock.assert_called_once_with(queue_event, self.env.user.id)
        with_delay_mock.assert_called_once_with(
            queue_event,
            identity_key=f"webhook_inbound_event_process:{queue_event.id}",
        )
        delayed.process_event.assert_called_once_with()

        handler = self._create_handler(direction="inbound")
        rule = self._create_inbound_rule(handler, action_type="done")
        reset_event = self._create_inbound_event(
            endpoint,
            handler=handler,
            state="dead_letter",
            processing_error="boom",
            processing_note="failed once",
            processed_at=fields.Datetime.now(),
            matched_inbound_rule_id=rule.id,
        )

        self.assertTrue(reset_event.action_reset_to_received())
        self.assertEqual(reset_event.state, "received")
        self.assertFalse(reset_event.processing_error)
        self.assertFalse(reset_event.processing_note)
        self.assertFalse(reset_event.processed_at)
        self.assertFalse(reset_event.matched_inbound_rule_id)

        rule = self._create_inbound_rule(handler, action_type="done")
        self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "resolved_value",
                "source_expression": "customer_name",
                "operator": "is_set",
            }
        )
        self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "resolved_value",
                "source_expression": "missing_value",
                "operator": "not_set",
            }
        )
        self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "semantic_field",
                "source_expression": "topic",
                "operator": "equals",
                "expected_value": "partner.sync",
            }
        )
        not_equals = self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "event_field",
                "source_expression": "delivery_id",
                "operator": "not_equals",
                "expected_value": "different-delivery",
            }
        )

        condition_event = self._create_inbound_event(
            endpoint,
            topic="partner.sync",
            delivery_id="DEL-2",
            resolved_values={"customer_name": "Alice Example"},
        )

        self.assertFalse(
            condition_event._resolve_inbound_source_value("unsupported", "topic")
        )
        self.assertTrue(all(condition_event.rule_execution_ids.browse()))
        self.assertTrue(condition_event._inbound_condition_matches(not_equals))
        for condition in rule.condition_ids - not_equals:
            self.assertTrue(condition_event._inbound_condition_matches(condition))

        unsupported_condition = Mock(
            source_kind="semantic_field",
            source_expression="topic",
            operator="unsupported",
            expected_value=False,
        )
        with self.assertRaisesRegex(
            ValidationError, "Unsupported inbound rule condition"
        ):
            condition_event._inbound_condition_matches(unsupported_condition)

    def test_model_driven_handler_additional_action_branches(self):
        no_match_handler = self._create_handler(direction="inbound")
        no_match_rule = self._create_inbound_rule(no_match_handler, action_type="done")
        self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": no_match_rule.id,
                "source_kind": "semantic_field",
                "source_expression": "topic",
                "operator": "equals",
                "expected_value": "partner.expected",
            }
        )
        no_match_event = self._create_inbound_event(
            self._create_inbound_endpoint(handler=no_match_handler),
            handler=no_match_handler,
            topic="partner.actual",
        )

        no_match_result = no_match_event._execute_model_driven_handler(no_match_handler)

        self.assertEqual(no_match_result["status"], "done")
        self.assertIn("stored only", no_match_result["note"])
        self.assertFalse(no_match_event.rule_execution_ids)

        update_handler = self._create_handler(direction="inbound")
        update_rule = self._create_inbound_rule(
            update_handler,
            action_type="update_record",
            target_model_name="res.partner",
        )
        self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": update_rule.id,
                "source_kind": "semantic_field",
                "source_expression": "topic",
                "operator": "equals",
                "expected_value": "partner.sync",
            }
        )
        self.env["webhook.handler.inbound.rule.lookup"].create(
            {
                "rule_id": update_rule.id,
                "target_field_name": "ref",
                "source_kind": "resolved_value",
                "source_expression": "external_ref",
            }
        )
        self.env["webhook.handler.inbound.rule.assignment"].create(
            {
                "rule_id": update_rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "resolved_value",
                "source_expression": "customer_name",
            }
        )
        update_event = self._create_inbound_event(
            self._create_inbound_endpoint(handler=update_handler),
            handler=update_handler,
            topic="partner.sync",
            resolved_values={
                "external_ref": "EXT-MISSING",
                "customer_name": "Missing Partner",
            },
        )

        with self.assertRaisesRegex(
            ValidationError, "No target record matched inbound update rule"
        ):
            update_event._execute_model_driven_handler(update_handler)

        self.assertEqual(update_event.rule_execution_ids.rule_id, update_rule)
        self.assertEqual(update_event.rule_execution_ids.state, "error")
        self.assertIn(
            "No target record matched inbound update rule",
            update_event.rule_execution_ids.error,
        )

        queue_handler = self._create_handler(direction="inbound")
        outbound_endpoint = self._create_outbound_endpoint()
        queue_rule = self._create_inbound_rule(
            queue_handler,
            action_type="queue_outbound",
            outbound_endpoint_id=outbound_endpoint.id,
        )
        self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": queue_rule.id,
                "source_kind": "semantic_field",
                "source_expression": "topic",
                "operator": "equals",
                "expected_value": "partner.sync",
            }
        )
        self.env["webhook.handler.inbound.rule.assignment"].create(
            {
                "rule_id": queue_rule.id,
                "target_kind": "context_key",
                "target_expression": "trace_id",
                "source_kind": "literal",
                "literal_value": "trace-1",
            }
        )
        self.env["webhook.handler.inbound.rule.assignment"].create(
            {
                "rule_id": queue_rule.id,
                "target_kind": "context_key",
                "target_expression": "payload",
                "source_kind": "literal",
                "literal_value": '{"count": 2}',
            }
        )
        queue_event = self._create_inbound_event(
            self._create_inbound_endpoint(handler=queue_handler),
            handler=queue_handler,
            topic="partner.sync",
        )

        with patch.object(
            type(self.env["webhook.outbound.delivery"]),
            "action_queue_delivery",
            autospec=True,
            return_value=True,
        ) as queue_delivery_mock:
            queue_result = queue_event._execute_model_driven_handler(queue_handler)

        queued_delivery = self.env["webhook.outbound.delivery"].search(
            [("endpoint_id", "=", outbound_endpoint.id)],
            order="id desc",
            limit=1,
        )
        context_values = {
            line.key_name: line.literal_value
            for line in queued_delivery.context_line_ids
        }

        self.assertEqual(queue_result["status"], "done")
        self.assertEqual(queue_result["matched_rule_id"], queue_rule.id)
        queue_delivery_mock.assert_called_once()
        self.assertEqual(context_values["trace_id"], "trace-1")
        self.assertEqual(json.loads(context_values["payload"]), {"count": 2})
        self.assertEqual(
            queue_event.rule_execution_ids.record_reference,
            f"webhook.outbound.delivery:{queued_delivery.id}",
        )

    def test_process_event_handles_remaining_result_shapes(self):
        terminal_endpoint = self._create_inbound_endpoint()
        done_event = self._create_inbound_event(terminal_endpoint, state="done")
        rejected_event = self._create_inbound_event(
            terminal_endpoint,
            state="rejected",
        )
        dead_letter_event = self._create_inbound_event(
            terminal_endpoint,
            state="dead_letter",
        )

        self.assertTrue(done_event.process_event())
        self.assertTrue(rejected_event.process_event())
        self.assertTrue(dead_letter_event.process_event())
        self.assertEqual(done_event.state, "done")
        self.assertEqual(rejected_event.state, "rejected")
        self.assertEqual(dead_letter_event.state, "dead_letter")

        handler = self._create_handler(direction="inbound")
        endpoint = self._create_inbound_endpoint(handler=handler)

        received_event = self._create_inbound_event(endpoint, handler=handler)
        with patch.object(
            type(handler),
            "execute_inbound",
            autospec=True,
            return_value={"status": "received", "note": "Hold for later"},
        ):
            received_event.process_event()
        self.assertEqual(received_event.state, "received")
        self.assertEqual(received_event.processing_note, "Hold for later")
        self.assertFalse(received_event.processed_at)

        done_result_event = self._create_inbound_event(endpoint, handler=handler)
        with patch.object(
            type(handler),
            "execute_inbound",
            autospec=True,
            return_value={"status": "done", "note": "Processed"},
        ):
            done_result_event.process_event()
        self.assertEqual(done_result_event.state, "done")
        self.assertEqual(done_result_event.processing_note, "Processed")
        self.assertTrue(done_result_event.processed_at)

        false_result_event = self._create_inbound_event(endpoint, handler=handler)
        with patch.object(
            type(handler),
            "execute_inbound",
            autospec=True,
            return_value=False,
        ):
            false_result_event.process_event()
        self.assertEqual(false_result_event.state, "received")
        self.assertFalse(false_result_event.processed_at)

        truthy_result_event = self._create_inbound_event(endpoint, handler=handler)
        with patch.object(
            type(handler),
            "execute_inbound",
            autospec=True,
            return_value=True,
        ):
            truthy_result_event.process_event()
        self.assertEqual(truthy_result_event.state, "done")
        self.assertFalse(truthy_result_event.processing_note)
        self.assertTrue(truthy_result_event.processed_at)

    def test_process_event_marks_done_when_no_handler_is_resolved(self):
        endpoint = self._create_inbound_endpoint()
        event = self._create_inbound_event(endpoint)

        event.process_event()

        self.assertEqual(event.state, "done")
        self.assertFalse(event.processing_error)
        self.assertIn("stored only", event.processing_note)
        self.assertTrue(event.processed_at)

    def test_process_event_handles_dead_letter_and_retry_rule_results(self):
        dead_letter_handler = self._create_handler(direction="inbound")
        dead_letter_rule = self._create_inbound_rule(
            dead_letter_handler,
            action_type="dead_letter",
            note="Moved to dead letter",
        )
        dead_letter_endpoint = self._create_inbound_endpoint(
            handler=dead_letter_handler
        )
        dead_letter_event = self._create_inbound_event(
            dead_letter_endpoint,
            handler=dead_letter_handler,
        )

        dead_letter_event.process_event()

        self.assertEqual(dead_letter_event.state, "dead_letter")
        self.assertEqual(dead_letter_event.processing_note, "Moved to dead letter")
        self.assertEqual(dead_letter_event.matched_inbound_rule_id, dead_letter_rule)

        retry_handler = self._create_handler(direction="inbound")
        retry_rule = self._create_inbound_rule(
            retry_handler,
            action_type="retry",
            note="Retry later",
            retry_seconds=15,
        )
        retry_endpoint = self._create_inbound_endpoint(handler=retry_handler)
        retry_event = self._create_inbound_event(retry_endpoint, handler=retry_handler)

        with self.assertRaisesRegex(RetryableJobError, "Retry later"):
            retry_event.process_event()

        self.assertEqual(retry_event.state, "received")
        self.assertEqual(retry_event.processing_note, "Retry later")
        self.assertEqual(retry_event.matched_inbound_rule_id, retry_rule)

    def test_process_event_marks_error_when_handler_raises(self):
        handler = self._create_handler(
            direction="inbound",
            execution_mode="python",
            python_model_name="res.partner",
            python_method_name="missing_webhook_callback",
        )
        endpoint = self._create_inbound_endpoint(handler=handler)
        event = self._create_inbound_event(endpoint, handler=handler)

        with self.assertRaisesRegex(ValidationError, "could not be found"):
            event.process_event()

        self.assertEqual(event.state, "error")
        self.assertIn("missing_webhook_callback", event.processing_error)
