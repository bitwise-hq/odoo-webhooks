import hashlib
import json

from odoo import SUPERUSER_ID
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
