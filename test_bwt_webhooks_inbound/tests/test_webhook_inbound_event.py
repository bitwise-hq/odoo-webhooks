"""Behavioral tests for :class:`webhook.inbound.event`.

The inbound event model is the heart of the inbound pipeline: it
parses incoming requests, persists their normalized form, exposes
helpers for handler rules, and drives the queue-job-backed processing
lifecycle.
"""

import hashlib
import json
from unittest.mock import Mock, patch

from psycopg2 import IntegrityError

from odoo import SUPERUSER_ID, fields
from odoo.exceptions import ValidationError

from odoo.addons.queue_job.exception import RetryableJobError
from odoo.addons.bwt_webhooks_core.exceptions import (
    WebhookPayloadValidationError,
    WebhookValidationError,
)
from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestInboundEventPayloadParsing(WebhookTestCase):
    """``_parse_payload`` handles empty, valid and broken JSON inputs."""

    def setUp(self):
        super().setUp()
        self.event_model = self.env["bwt.webhook.inbound.event"]

    def test_empty_string_returns_empty_dict(self):
        self.assertEqual(self.event_model._parse_payload(""), {})

    def test_broken_json_returns_falsy_when_not_strict(self):
        self.assertFalse(self.event_model._parse_payload("{broken json"))

    def test_broken_json_raises_when_raise_on_invalid(self):
        with self.assertRaisesRegex(WebhookPayloadValidationError, "valid JSON"):
            self.event_model._parse_payload("{broken json", raise_on_invalid=True)


class TestInboundEventResolvedValuesAccess(WebhookTestCase):
    """``get_resolved_values`` / ``get_resolved_value`` read the stored JSON."""

    def setUp(self):
        super().setUp()
        endpoint = self.factory.inbound_endpoint()
        self.event = self.factory.inbound_event(
            endpoint,
            resolved_values={
                "customer_name": "Alice Example",
                "external_ref": "EXT-1",
            },
        )

    def test_broken_resolved_values_json_returns_empty_dict(self):
        self.event.resolved_values_json = "{broken json"

        self.assertEqual(self.event.get_resolved_values(), {})

    def test_get_resolved_value_returns_default_when_key_missing(self):
        self.event.resolved_values_json = "{broken json"

        self.assertEqual(self.event.get_resolved_value("customer_name", "fallback"), "fallback")

    def test_get_resolved_value_returns_stored_value(self):
        self.assertEqual(self.event.get_resolved_value("customer_name"), "Alice Example")


class TestInboundEventLiteralValueDecoding(WebhookTestCase):
    """``_decode_literal_value`` returns parsed JSON when possible."""

    def setUp(self):
        super().setUp()
        endpoint = self.factory.inbound_endpoint()
        self.event = self.factory.inbound_event(endpoint)

    def test_json_string_is_decoded_to_python_value(self):
        self.assertEqual(self.event._decode_literal_value('{"flag": true}'), {"flag": True})

    def test_plain_text_is_returned_unchanged(self):
        self.assertEqual(self.event._decode_literal_value("plain text"), "plain text")


class TestInboundEventSourceValueResolution(WebhookTestCase):
    """``_resolve_inbound_source_value`` dispatches per ``source_kind``."""

    def setUp(self):
        super().setUp()
        endpoint = self.factory.inbound_endpoint()
        self.event = self.factory.inbound_event(
            endpoint,
            topic="partner.sync",
            delivery_id="DEL-1",
            resolved_values={
                "customer_name": "Alice Example",
                "external_ref": "EXT-1",
            },
        )

    def test_literal_kind_coerces_numeric_string_to_int(self):
        self.assertEqual(
            self.event._resolve_inbound_source_value("literal", literal_value="42"),
            42,
        )

    def test_resolved_value_kind_returns_stored_resolved_value(self):
        self.assertEqual(
            self.event._resolve_inbound_source_value("resolved_value", "customer_name"),
            "Alice Example",
        )

    def test_semantic_field_kind_returns_event_semantic_field(self):
        self.assertEqual(
            self.event._resolve_inbound_source_value("semantic_field", "topic"),
            "partner.sync",
        )

    def test_event_field_kind_returns_event_database_field(self):
        self.assertEqual(
            self.event._resolve_inbound_source_value("event_field", "delivery_id"),
            "DEL-1",
        )

    def test_unsupported_kind_returns_falsy(self):
        self.assertFalse(self.event._resolve_inbound_source_value("unsupported", "topic"))


class TestInboundEventConditionMatching(WebhookTestCase):
    """``_inbound_condition_matches`` honors every supported operator."""

    def setUp(self):
        super().setUp()
        self.handler = self.factory.handler(direction="inbound")
        self.rule = self.factory.inbound_rule(self.handler, action_type="done")
        endpoint = self.factory.inbound_endpoint(handler=self.handler)
        self.event = self.factory.inbound_event(
            endpoint,
            handler=self.handler,
            topic="partner.sync",
            delivery_id="DEL-2",
            resolved_values={"customer_name": "Alice Example"},
        )
        self.condition_model = self.env["bwt.webhook.inbound.handler.rule.condition"]

    def _condition(self, **values):
        return self.condition_model.create({"rule_id": self.rule.id, **values})

    def test_is_set_operator_matches_present_resolved_value(self):
        condition = self._condition(
            source_kind="resolved_value",
            source_expression="customer_name",
            operator="is_set",
        )

        self.assertTrue(self.event._inbound_condition_matches(condition))

    def test_not_set_operator_matches_missing_resolved_value(self):
        condition = self._condition(
            source_kind="resolved_value",
            source_expression="missing_value",
            operator="not_set",
        )

        self.assertTrue(self.event._inbound_condition_matches(condition))

    def test_equals_operator_matches_semantic_field(self):
        condition = self._condition(
            source_kind="semantic_field",
            source_expression="topic",
            operator="equals",
            expected_value="partner.sync",
        )

        self.assertTrue(self.event._inbound_condition_matches(condition))

    def test_contains_operator_matches_semantic_field_substring(self):
        condition = self._condition(
            source_kind="semantic_field",
            source_expression="topic",
            operator="contains",
            expected_value="partner",
        )

        self.assertTrue(self.event._inbound_condition_matches(condition))

    def test_not_equals_operator_matches_event_field(self):
        condition = self._condition(
            source_kind="event_field",
            source_expression="delivery_id",
            operator="not_equals",
            expected_value="different-delivery",
        )

        self.assertTrue(self.event._inbound_condition_matches(condition))

    def test_unsupported_operator_raises(self):
        unsupported = Mock(
            source_kind="semantic_field",
            source_expression="topic",
            operator="unsupported",
            expected_value=False,
        )

        with self.assertRaisesRegex(ValidationError, "Unsupported inbound rule condition"):
            self.event._inbound_condition_matches(unsupported)


class TestInboundEventLookupDomainAndAssignmentBuild(WebhookTestCase):
    """``_build_inbound_lookup_domain`` and ``_build_inbound_assignment_values`` shape rule inputs."""

    def setUp(self):
        super().setUp()
        self.handler = self.factory.handler(direction="inbound")
        self.rule = self.factory.inbound_rule(self.handler, action_type="done")
        endpoint = self.factory.inbound_endpoint(handler=self.handler)
        self.event = self.factory.inbound_event(
            endpoint,
            handler=self.handler,
            resolved_values={
                "customer_name": "Alice Example",
                "external_ref": "EXT-1",
            },
        )
        self.env["bwt.webhook.inbound.handler.rule.lookup"].create(
            {
                "rule_id": self.rule.id,
                "target_field_name": "ref",
                "source_kind": "resolved_value",
                "source_expression": "external_ref",
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
            {
                "rule_id": self.rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "resolved_value",
                "source_expression": "customer_name",
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
            {
                "rule_id": self.rule.id,
                "target_kind": "context_key",
                "target_expression": "payload",
                "source_kind": "literal",
                "literal_value": '{"flag": true}',
            }
        )

    def test_lookup_domain_uses_target_field_and_resolved_value(self):
        self.assertEqual(
            self.event._build_inbound_lookup_domain(self.rule),
            [("ref", "=", "EXT-1")],
        )

    def test_assignment_values_for_field_target_returns_field_dict(self):
        self.assertEqual(
            self.event._build_inbound_assignment_values(self.rule, target_kind="field"),
            {"name": "Alice Example"},
        )

    def test_assignment_values_for_context_key_target_decodes_literal(self):
        self.assertEqual(
            self.event._build_inbound_assignment_values(self.rule, target_kind="context_key"),
            {"payload": {"flag": True}},
        )


class TestInboundEventReceiveWebhookRequest(WebhookTestCase):
    """``_receive_webhook_request`` creates primary, replay and duplicate records."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self.factory.endpoint_source(
            self.endpoint,
            field_name="delivery_key",
            source_kind="header",
            header_name="X-Delivery-Id",
        )
        self.factory.endpoint_source(
            self.endpoint,
            field_name="event_key",
            source_kind="header",
            header_name="X-Event-Id",
        )
        self.factory.semantic_binding(self.endpoint, semantic_name="delivery_id", value_key="delivery_key")
        self.factory.semantic_binding(self.endpoint, semantic_name="event_id", value_key="event_key")
        self.endpoint.write(
            {
                "delivery_identity_policy": "delivery_id",
                "replay_identity_policy": "event_id",
            }
        )
        self.event_model = self.env["bwt.webhook.inbound.event"]
        self.first = self.event_model._receive_webhook_request(
            self.endpoint,
            b"{}",
            {"X-Delivery-Id": "delivery-1", "X-Event-Id": "event-1"},
        )
        self.second = self.event_model._receive_webhook_request(
            self.endpoint,
            b"{}",
            {"X-Delivery-Id": "delivery-2", "X-Event-Id": "event-1"},
        )
        self.duplicate = self.event_model._receive_webhook_request(
            self.endpoint,
            b"{}",
            {"X-Delivery-Id": "delivery-1", "X-Event-Id": "event-1"},
        )

    def test_first_delivery_is_recorded_as_primary(self):
        self.assertEqual(self.first.delivery_identity_key, "delivery-1")
        self.assertEqual(self.first.delivery_kind, "primary")

    def test_second_delivery_with_same_event_id_is_recorded_as_replay(self):
        self.assertEqual(self.second.delivery_identity_key, "delivery-2")
        self.assertEqual(self.second.delivery_kind, "replay")
        self.assertEqual(self.second.replayed_from_event_id, self.first)

    def test_duplicate_delivery_returns_existing_event_record(self):
        self.assertEqual(self.duplicate, self.first)
        self.assertEqual(
            self.event_model.search_count([("endpoint_id", "=", self.endpoint.id)]),
            2,
        )

    def test_queue_job_identity_key_uses_event_id(self):
        self.assertEqual(
            self.first.queue_job_identity_key,
            f"webhook_inbound_event_process:{self.first.id}",
        )

    def test_queue_job_action_domain_targets_process_event_method(self):
        self.assertEqual(
            self.first._get_queue_job_action_domain(),
            [
                ("identity_key", "=", f"webhook_inbound_event_process:{self.first.id}"),
                ("model_name", "=", "bwt.webhook.inbound.event"),
                ("method_name", "=", "process_event"),
            ],
        )

    def test_action_view_queue_jobs_returns_named_action_with_domain(self):
        action = self.first.action_view_queue_jobs()

        self.assertEqual(action["name"], "Inbound Queue Jobs")
        self.assertEqual(action["domain"], self.first._get_queue_job_action_domain())

    def test_concurrent_create_integrity_error_returns_existing_event(self):
        """Two concurrent receivers race on the same delivery identity key.

        When the second creation fails with IntegrityError because the racer
        already inserted the row, the receiver searches it back instead of
        propagating the error.
        """
        racer = self.event_model._receive_webhook_request(
            self.endpoint,
            b"{}",
            {"X-Delivery-Id": "delivery-race", "X-Event-Id": "event-race"},
        )

        EventModel = type(self.event_model)
        real_search = EventModel.search
        state = {"created": False}

        def fake_search(model, domain, *args, **kwargs):
            if not state["created"] and ("delivery_identity_key", "=", "delivery-race") in domain:
                return model.browse()
            return real_search(model, domain, *args, **kwargs)

        def fake_create(model, values):
            state["created"] = True
            raise IntegrityError("duplicate key value violates unique constraint")

        with patch.object(EventModel, "search", autospec=True, side_effect=fake_search):
            with patch.object(EventModel, "create", autospec=True, side_effect=fake_create):
                recovered = self.event_model._receive_webhook_request(
                    self.endpoint,
                    b"{}",
                    {
                        "X-Delivery-Id": "delivery-race",
                        "X-Event-Id": "event-race",
                    },
                )

        self.assertEqual(recovered, racer)

    def test_concurrent_race_does_not_requeue_already_processed_racer(self):
        """If the racer is already processed, recovery does not re-enqueue it."""
        racer = self.event_model._receive_webhook_request(
            self.endpoint,
            b"{}",
            {
                "X-Delivery-Id": "delivery-processed-race",
                "X-Event-Id": "event-processed-race",
            },
        )
        racer.write({"state": "done"})

        EventModel = type(self.event_model)
        real_search = EventModel.search
        state = {"created": False}

        def fake_search(model, domain, *args, **kwargs):
            if (
                not state["created"]
                and (
                    "delivery_identity_key",
                    "=",
                    "delivery-processed-race",
                )
                in domain
            ):
                return model.browse()
            return real_search(model, domain, *args, **kwargs)

        def fake_create(model, values):
            state["created"] = True
            raise IntegrityError("duplicate key value violates unique constraint")

        with patch.object(EventModel, "search", autospec=True, side_effect=fake_search):
            with patch.object(EventModel, "create", autospec=True, side_effect=fake_create):
                with patch.object(EventModel, "_queue_processing", autospec=True) as queue_mock:
                    recovered = self.event_model._receive_webhook_request(
                        self.endpoint,
                        b"{}",
                        {
                            "X-Delivery-Id": "delivery-processed-race",
                            "X-Event-Id": "event-processed-race",
                        },
                    )

        self.assertEqual(recovered, racer)
        queue_mock.assert_not_called()


class TestInboundEventReceiveRejectsInvalidPayload(WebhookTestCase):
    """A malformed request body is rejected and persisted with rejection metadata."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self.event_model = self.env["bwt.webhook.inbound.event"]
        self.body = b"{broken json"
        self.headers = {"X-Request-Id": "req-1"}

    def test_invalid_payload_raises_payload_validation_error(self):
        with self.assertRaisesRegex(WebhookPayloadValidationError, "valid JSON"):
            self.event_model._receive_webhook_request(self.endpoint, self.body, self.headers)

    def test_invalid_payload_persists_rejected_event_with_metadata(self):
        with self.assertRaisesRegex(WebhookPayloadValidationError, "valid JSON"):
            self.event_model._receive_webhook_request(self.endpoint, self.body, self.headers)

        rejected = self.event_model.search(
            [("endpoint_id", "=", self.endpoint.id), ("state", "=", "rejected")],
            order="id desc",
            limit=1,
        )
        self.assertTrue(rejected)
        self.assertEqual(rejected.rejection_category, "payload")
        self.assertIn("valid JSON", rejected.rejection_reason)
        self.assertEqual(json.loads(rejected.payload_json), {})
        self.assertEqual(rejected.body_sha256, hashlib.sha256(self.body).hexdigest())


class TestInboundEventReceiveRejectsWebhookValidation(WebhookTestCase):
    """Webhook validation failures are persisted as rejected events."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self.event_model = self.env["bwt.webhook.inbound.event"]

    def test_webhook_validation_error_persists_rejected_event(self):
        body = b'{"ok": true}'
        headers = {"X-Request-Id": "req-webhook-validation"}
        with patch.object(
            type(self.endpoint),
            "_validate_inbound_request",
            autospec=True,
            side_effect=WebhookValidationError("signature mismatch"),
        ):
            with self.assertRaisesRegex(WebhookValidationError, "signature mismatch"):
                self.event_model._receive_webhook_request(self.endpoint, body, headers)

        rejected = self.event_model.search(
            [
                ("endpoint_id", "=", self.endpoint.id),
                ("state", "=", "rejected"),
                ("rejection_reason", "=", "signature mismatch"),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(rejected)


class TestInboundEventLogRejectedRequest(WebhookTestCase):
    """``_log_rejected_request`` works even when identity resolution fails."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self.event_model = self.env["bwt.webhook.inbound.event"]

    def test_broken_identity_resolution_still_persists_rejection(self):
        with patch.object(
            type(self.endpoint),
            "_resolve_delivery_identity",
            autospec=True,
            side_effect=ValidationError("delivery identity missing"),
        ):
            with patch.object(
                type(self.endpoint),
                "_resolve_replay_identity",
                autospec=True,
                side_effect=ValidationError("replay identity missing"),
            ):
                rejected = self.event_model._log_rejected_request(
                    self.endpoint,
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

    def test_endpointless_rejection_uses_company_default_and_serializes_payload(self):
        with patch.object(
            type(self.event_model),
            "create",
            autospec=True,
            side_effect=lambda model, values: values,
        ):
            endpointless_vals = self.event_model._log_rejected_request(
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

    def test_duplicate_rejected_log_returns_existing_record(self):
        existing = self.factory.inbound_event(self.endpoint)
        with patch.object(type(self.event_model), "with_user", autospec=True, return_value=self.event_model):
            with patch.object(type(self.event_model), "create", autospec=True, side_effect=IntegrityError("duplicate")):
                with patch.object(type(self.event_model), "search", autospec=True, return_value=existing) as search_mock:
                    recovered = self.event_model._log_rejected_request(
                        self.endpoint,
                        b"{}",
                        {"X-Test": "dup"},
                        rejection_reason="duplicate",
                    )

        self.assertEqual(recovered, existing)
        search_mock.assert_called_once()


class TestInboundEventActionQueueProcessing(WebhookTestCase):
    """``action_queue_processing`` enqueues ``process_event`` under the superuser."""

    def test_queue_processing_runs_under_superuser_and_clears_processing_error(self):
        endpoint = self.factory.inbound_endpoint()
        event = self.factory.inbound_event(
            endpoint,
            processing_error="stale error",
        )
        delayed = Mock()

        with patch.object(type(event), "with_user", autospec=True, return_value=event) as with_user_mock:
            with patch.object(type(event), "with_delay", autospec=True, return_value=delayed) as with_delay_mock:
                self.assertTrue(event.action_queue_processing())

        self.assertFalse(event.processing_error)
        with_user_mock.assert_called_once_with(event, SUPERUSER_ID)
        with_delay_mock.assert_called_once_with(
            event,
            identity_key=f"webhook_inbound_event_process:{event.id}",
        )
        delayed.process_event.assert_called_once_with()


class TestInboundEventActionResetToReceived(WebhookTestCase):
    """``action_reset_to_received`` clears terminal-state metadata."""

    def test_reset_clears_state_processing_and_matched_rule(self):
        handler = self.factory.handler(direction="inbound")
        rule = self.factory.inbound_rule(handler, action_type="done")
        endpoint = self.factory.inbound_endpoint(handler=handler)
        event = self.factory.inbound_event(
            endpoint,
            handler=handler,
            state="dead_letter",
            processing_error="boom",
            processing_note="failed once",
            processed_at=fields.Datetime.now(),
            matched_inbound_rule_id=rule.id,
        )

        self.assertTrue(event.action_reset_to_received())

        self.assertEqual(event.state, "received")
        self.assertFalse(event.processing_error)
        self.assertFalse(event.processing_note)
        self.assertFalse(event.processed_at)
        self.assertFalse(event.matched_inbound_rule_id)


class TestInboundEventProcessEventTerminalStates(WebhookTestCase):
    """``process_event`` is a no-op for already-terminal records."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_done_event_passthrough_keeps_state(self):
        event = self.factory.inbound_event(self.endpoint, state="done")

        self.assertTrue(event.process_event())
        self.assertEqual(event.state, "done")

    def test_rejected_event_passthrough_keeps_state(self):
        event = self.factory.inbound_event(self.endpoint, state="rejected")

        self.assertTrue(event.process_event())
        self.assertEqual(event.state, "rejected")

    def test_dead_letter_event_passthrough_keeps_state(self):
        event = self.factory.inbound_event(self.endpoint, state="dead_letter")

        self.assertTrue(event.process_event())
        self.assertEqual(event.state, "dead_letter")


class TestInboundEventProcessEventResultShapes(WebhookTestCase):
    """``process_event`` honors every documented handler return shape."""

    def setUp(self):
        super().setUp()
        self.handler = self.factory.handler(direction="inbound")
        self.endpoint = self.factory.inbound_endpoint(handler=self.handler)

    def _patch_execute(self, return_value):
        return patch.object(
            type(self.handler),
            "execute_inbound",
            autospec=True,
            return_value=return_value,
        )

    def test_received_status_keeps_state_and_records_note(self):
        event = self.factory.inbound_event(self.endpoint, handler=self.handler)

        with self._patch_execute({"status": "received", "note": "Hold for later"}):
            event.process_event()

        self.assertEqual(event.state, "received")
        self.assertEqual(event.processing_note, "Hold for later")
        self.assertFalse(event.processed_at)

    def test_done_status_marks_event_done_with_note_and_processed_at(self):
        event = self.factory.inbound_event(self.endpoint, handler=self.handler)

        with self._patch_execute({"status": "done", "note": "Processed"}):
            event.process_event()

        self.assertEqual(event.state, "done")
        self.assertEqual(event.processing_note, "Processed")
        self.assertTrue(event.processed_at)

    def test_falsy_handler_result_keeps_state_received(self):
        event = self.factory.inbound_event(self.endpoint, handler=self.handler)

        with self._patch_execute(False):
            event.process_event()

        self.assertEqual(event.state, "received")
        self.assertFalse(event.processed_at)

    def test_truthy_handler_result_marks_event_done_without_note(self):
        event = self.factory.inbound_event(self.endpoint, handler=self.handler)

        with self._patch_execute(True):
            event.process_event()

        self.assertEqual(event.state, "done")
        self.assertFalse(event.processing_note)
        self.assertTrue(event.processed_at)


class TestInboundEventProcessEventNoHandler(WebhookTestCase):
    """A handlerless endpoint marks the event done with a "stored only" note."""

    def test_endpoint_without_handler_marks_event_done_stored_only(self):
        endpoint = self.factory.inbound_endpoint()
        event = self.factory.inbound_event(endpoint)

        event.process_event()

        self.assertEqual(event.state, "done")
        self.assertFalse(event.processing_error)
        self.assertIn("stored only", event.processing_note)
        self.assertTrue(event.processed_at)


class TestInboundEventProcessEventDeadLetterRule(WebhookTestCase):
    """A matching ``dead_letter`` rule transitions the event to ``dead_letter``."""

    def test_dead_letter_rule_moves_event_to_dead_letter_state(self):
        handler = self.factory.handler(direction="inbound")
        rule = self.factory.inbound_rule(
            handler,
            action_type="dead_letter",
            note="Moved to dead letter",
        )
        endpoint = self.factory.inbound_endpoint(handler=handler)
        event = self.factory.inbound_event(endpoint, handler=handler)

        event.process_event()

        self.assertEqual(event.state, "dead_letter")
        self.assertEqual(event.processing_note, "Moved to dead letter")
        self.assertEqual(event.matched_inbound_rule_id, rule)


class TestInboundEventProcessEventRetryRule(WebhookTestCase):
    """A matching ``retry`` rule raises ``RetryableJobError`` and stays ``received``."""

    def test_retry_rule_raises_retryable_job_error_and_keeps_state(self):
        handler = self.factory.handler(direction="inbound")
        rule = self.factory.inbound_rule(
            handler,
            action_type="retry",
            note="Retry later",
            retry_seconds=15,
        )
        endpoint = self.factory.inbound_endpoint(handler=handler)
        event = self.factory.inbound_event(endpoint, handler=handler)

        with self.assertRaisesRegex(RetryableJobError, "Retry later"):
            event.process_event()

        self.assertEqual(event.state, "received")
        self.assertEqual(event.processing_note, "Retry later")
        self.assertEqual(event.matched_inbound_rule_id, rule)


class TestInboundEventProcessEventHandlerError(WebhookTestCase):
    """A python handler with a missing method marks the event ``error``."""

    def test_missing_python_method_raises_and_marks_event_as_error(self):
        handler = self.factory.handler(
            direction="inbound",
            execution_mode="python",
            python_model_name="res.partner",
            python_method_name="missing_webhook_callback",
        )
        endpoint = self.factory.inbound_endpoint(handler=handler)
        event = self.factory.inbound_event(endpoint, handler=handler)

        with self.assertRaisesRegex(ValidationError, "could not be found"):
            event.process_event()

        self.assertEqual(event.state, "error")
        self.assertIn("missing_webhook_callback", event.processing_error)


class TestInboundEventModelDrivenNoMatch(WebhookTestCase):
    """``_execute_model_driven_handler`` with no matching rule marks the event done."""

    def test_no_matching_rule_marks_event_done_stored_only(self):
        handler = self.factory.handler(direction="inbound")
        rule = self.factory.inbound_rule(handler, action_type="done")
        self.env["bwt.webhook.inbound.handler.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "semantic_field",
                "source_expression": "topic",
                "operator": "equals",
                "expected_value": "partner.expected",
            }
        )
        endpoint = self.factory.inbound_endpoint(handler=handler)
        event = self.factory.inbound_event(endpoint, handler=handler, topic="partner.actual")

        result = event._execute_model_driven_handler(handler)

        self.assertEqual(result["status"], "done")
        self.assertIn("stored only", result["note"])
        self.assertFalse(event.rule_execution_ids)


class TestInboundEventModelDrivenUpdateRecordWithNoMatch(WebhookTestCase):
    """An ``update_record`` rule with a non-matching lookup raises and logs."""

    def test_non_matching_lookup_raises_and_logs_error_rule_execution(self):
        handler = self.factory.handler(direction="inbound")
        rule = self.factory.inbound_rule(
            handler,
            action_type="update_record",
            target_model_name="res.partner",
        )
        self.env["bwt.webhook.inbound.handler.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "semantic_field",
                "source_expression": "topic",
                "operator": "equals",
                "expected_value": "partner.sync",
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.lookup"].create(
            {
                "rule_id": rule.id,
                "target_field_name": "ref",
                "source_kind": "resolved_value",
                "source_expression": "external_ref",
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "resolved_value",
                "source_expression": "customer_name",
            }
        )
        endpoint = self.factory.inbound_endpoint(handler=handler)
        event = self.factory.inbound_event(
            endpoint,
            handler=handler,
            topic="partner.sync",
            resolved_values={
                "external_ref": "EXT-MISSING",
                "customer_name": "Missing Partner",
            },
        )

        with self.assertRaisesRegex(ValidationError, "No target record matched inbound update rule"):
            event._execute_model_driven_handler(handler)

        self.assertEqual(event.rule_execution_ids.rule_id, rule)
        self.assertEqual(event.rule_execution_ids.state, "error")
        self.assertIn(
            "No target record matched inbound update rule",
            event.rule_execution_ids.error,
        )


class TestInboundEventQueueJobObservability(WebhookTestCase):
    """``_compute_queue_job_*`` populates the related observability fields."""

    def test_compute_populates_identity_key_and_zero_count(self):
        endpoint = self.factory.inbound_endpoint()
        event = self.factory.inbound_event(endpoint)

        event._compute_queue_job_identity_key()
        event._compute_queue_job_observability()

        self.assertEqual(
            event.queue_job_identity_key,
            f"webhook_inbound_event_process:{event.id}",
        )
        self.assertFalse(event.queue_job_ids)
        self.assertEqual(event.queue_job_count, 0)
        self.assertFalse(event.latest_queue_job_id)
        self.assertFalse(event.latest_queue_job_state)


class TestInboundEventQueueProcessingStateValidation(WebhookTestCase):
    """``action_queue_processing`` rejects events in non-queueable states."""

    def test_done_event_rejects_action_queue_processing(self):
        endpoint = self.factory.inbound_endpoint()
        event = self.factory.inbound_event(endpoint, state="done")

        with self.assertRaisesRegex(ValidationError, "Only received or failed webhook events"):
            event.action_queue_processing()


class TestInboundEventReceiveWithoutReplayPolicy(WebhookTestCase):
    """``_receive_webhook_request`` short-circuits when no replay policy is configured."""

    def test_endpoint_without_replay_policy_records_primary_delivery(self):
        endpoint = self.factory.inbound_endpoint()
        event = self.env["bwt.webhook.inbound.event"]._receive_webhook_request(endpoint, b"{}", {})

        self.assertEqual(event.delivery_kind, "primary")
        self.assertFalse(event.replay_identity_key)
        self.assertFalse(event.replayed_from_event_id)


class TestInboundEventReceiveDuplicateOnTerminalState(WebhookTestCase):
    """A duplicate request matching a terminal-state event returns it without re-queueing."""

    def test_duplicate_for_done_event_returns_existing_without_queueing(self):
        endpoint = self.factory.inbound_endpoint()
        event_model = self.env["bwt.webhook.inbound.event"]
        first = event_model._receive_webhook_request(endpoint, b'{"k": 1}', {})
        first.state = "done"
        body_for_dedupe = b'{"k": 1}'

        with patch.object(type(first), "_queue_processing", autospec=True) as queue_mock:
            duplicate = event_model._receive_webhook_request(endpoint, body_for_dedupe, {})

        self.assertEqual(duplicate, first)
        self.assertEqual(duplicate.state, "done")
        queue_mock.assert_not_called()


class TestInboundEventResetToReceivedStateValidation(WebhookTestCase):
    """``action_reset_to_received`` rejects events in non-retriable states."""

    def test_done_event_rejects_action_reset_to_received(self):
        endpoint = self.factory.inbound_endpoint()
        event = self.factory.inbound_event(endpoint, state="done")

        with self.assertRaisesRegex(ValidationError, "Only failed or dead-letter"):
            event.action_reset_to_received()


class TestInboundEventResolvedValuesEmpty(WebhookTestCase):
    """An event with no stored resolved values returns an empty dict."""

    def test_empty_resolved_values_json_returns_empty_dict(self):
        endpoint = self.factory.inbound_endpoint()
        event = self.factory.inbound_event(endpoint)
        event.resolved_values_json = False

        self.assertEqual(event.get_resolved_values(), {})


class TestInboundEventActionViewQueueJobsWithoutIdentityKey(WebhookTestCase):
    """An event without an identity key produces an empty queue-job action domain."""

    def test_event_without_identity_key_returns_empty_match_domain(self):
        endpoint = self.factory.inbound_endpoint()
        event = self.factory.inbound_event(endpoint)
        event.queue_job_identity_key = False

        self.assertEqual(event._get_queue_job_action_domain(), [("id", "=", 0)])


class TestInboundEventQueueJobObservabilityWithJobs(WebhookTestCase):
    """``_compute_queue_job_observability`` aggregates real queue jobs by identity key."""

    def test_compute_on_empty_recordset_does_not_search_jobs(self):
        empty = self.env["bwt.webhook.inbound.event"].browse([])

        empty._compute_queue_job_observability()

    def test_compute_collects_existing_queue_jobs_for_identity_key(self):
        endpoint = self.factory.inbound_endpoint()
        event = self.factory.inbound_event(endpoint)
        identity_key = event.queue_job_identity_key
        self.assertTrue(identity_key)
        QueueJob = self.env["queue.job"]
        job_a = QueueJob.with_context(
            _job_edit_sentinel=QueueJob.EDIT_SENTINEL
        ).create(
            {
                "uuid": "job-a-%s" % event.id,
                "identity_key": identity_key,
                "model_name": "bwt.webhook.inbound.event",
                "method_name": "process_event",
                "state": "done",
                "func_string": "ev.process_event()",
            }
        )
        job_b = QueueJob.with_context(
            _job_edit_sentinel=QueueJob.EDIT_SENTINEL
        ).create(
            {
                "uuid": "job-b-%s" % event.id,
                "identity_key": identity_key,
                "model_name": "bwt.webhook.inbound.event",
                "method_name": "process_event",
                "state": "pending",
                "func_string": "ev.process_event()",
            }
        )

        event.invalidate_recordset()

        self.assertEqual(event.queue_job_count, 2)
        self.assertEqual(event.queue_job_ids, job_a | job_b)
        self.assertIn(event.latest_queue_job_state, ("done", "pending"))


class TestInboundEventProcessEventDoneRule(WebhookTestCase):
    """A matching ``done`` rule transitions the event to ``done``."""

    def test_done_rule_marks_event_done_with_note(self):
        handler = self.factory.handler(direction="inbound")
        rule = self.factory.inbound_rule(handler, action_type="done", note="All good")
        endpoint = self.factory.inbound_endpoint(handler=handler)
        event = self.factory.inbound_event(endpoint, handler=handler)

        event.process_event()

        self.assertEqual(event.state, "done")
        self.assertEqual(event.processing_note, "All good")
        self.assertEqual(event.matched_inbound_rule_id, rule)


class TestInboundEventProcessEventCreateRecordRule(WebhookTestCase):
    """A matching ``create_record`` rule creates the target record and marks the event done."""

    def test_create_record_rule_creates_record_and_marks_done(self):
        handler = self.factory.handler(direction="inbound")
        rule = self.factory.inbound_rule(
            handler,
            action_type="create_record",
            target_model_name="res.partner",
        )
        self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "literal",
                "literal_value": '"Created Partner"',
            }
        )
        endpoint = self.factory.inbound_endpoint(handler=handler)
        event = self.factory.inbound_event(endpoint, handler=handler)

        event.process_event()

        self.assertEqual(event.state, "done")
        partner = self.env["res.partner"].search([("name", "=", "Created Partner")], limit=1)
        self.assertTrue(partner)


class TestInboundEventProcessEventUpdateRecordRule(WebhookTestCase):
    """A matching ``update_record`` rule writes to an existing target record."""

    def test_update_record_rule_writes_existing_record(self):
        partner = self.env["res.partner"].create({"name": "Original", "ref": "EXT-99"})
        handler = self.factory.handler(direction="inbound")
        rule = self.factory.inbound_rule(
            handler,
            action_type="update_record",
            target_model_name="res.partner",
        )
        self.env["bwt.webhook.inbound.handler.rule.lookup"].create(
            {
                "rule_id": rule.id,
                "target_field_name": "ref",
                "source_kind": "literal",
                "literal_value": '"EXT-99"',
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "literal",
                "literal_value": '"Updated Partner"',
            }
        )
        endpoint = self.factory.inbound_endpoint(handler=handler)
        event = self.factory.inbound_event(endpoint, handler=handler)

        event.process_event()

        self.assertEqual(event.state, "done")
        self.assertEqual(partner.name, "Updated Partner")


class TestInboundEventProcessEventUpsertRecordRule(WebhookTestCase):
    """A matching ``upsert_record`` rule updates when found and creates when missing."""

    def setUp(self):
        super().setUp()
        self.handler = self.factory.handler(direction="inbound")
        self.rule = self.factory.inbound_rule(
            self.handler,
            action_type="upsert_record",
            target_model_name="res.partner",
        )
        self.env["bwt.webhook.inbound.handler.rule.lookup"].create(
            {
                "rule_id": self.rule.id,
                "target_field_name": "ref",
                "source_kind": "literal",
                "literal_value": '"UPSERT-1"',
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
            {
                "rule_id": self.rule.id,
                "target_kind": "field",
                "target_expression": "ref",
                "source_kind": "literal",
                "literal_value": '"UPSERT-1"',
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
            {
                "rule_id": self.rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "literal",
                "literal_value": '"Upserted Partner"',
            }
        )
        self.endpoint = self.factory.inbound_endpoint(handler=self.handler)

    def test_upsert_creates_when_no_target_record_matches(self):
        event = self.factory.inbound_event(self.endpoint, handler=self.handler)

        event.process_event()

        self.assertEqual(event.state, "done")
        self.assertTrue(self.env["res.partner"].search([("ref", "=", "UPSERT-1"), ("name", "=", "Upserted Partner")]))

    def test_upsert_updates_existing_target_record(self):
        partner = self.env["res.partner"].create({"name": "Original", "ref": "UPSERT-1"})
        event = self.factory.inbound_event(self.endpoint, handler=self.handler)

        event.process_event()

        self.assertEqual(event.state, "done")
        self.assertEqual(partner.name, "Upserted Partner")


class TestInboundEventProcessingSeconds(WebhookTestCase):
    """``_compute_processing_seconds`` derives latency from received_at / processed_at."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_processing_seconds_is_zero_when_not_yet_processed(self):
        event = self.factory.inbound_event(self.endpoint)

        self.assertEqual(event.processing_seconds, 0.0)

    def test_processing_seconds_computed_from_timestamps(self):
        received = fields.Datetime.from_string("2026-01-01 10:00:00")
        processed = fields.Datetime.from_string("2026-01-01 10:00:30")
        event = self.factory.inbound_event(
            self.endpoint,
            received_at=received,
            processed_at=processed,
        )

        event.invalidate_recordset(["processing_seconds"])
        event._compute_processing_seconds()

        self.assertAlmostEqual(event.processing_seconds, 30.0)

    def test_processing_seconds_floored_at_zero_when_timestamps_inverted(self):
        received = fields.Datetime.from_string("2026-01-01 10:00:30")
        processed = fields.Datetime.from_string("2026-01-01 10:00:00")
        event = self.factory.inbound_event(
            self.endpoint,
            received_at=received,
            processed_at=processed,
        )

        event.invalidate_recordset(["processing_seconds"])
        event._compute_processing_seconds()

        self.assertEqual(event.processing_seconds, 0.0)

    def test_processing_seconds_true_branch_via_write(self):
        received = fields.Datetime.from_string("2026-01-01 10:00:00")
        processed = fields.Datetime.from_string("2026-01-01 10:00:30")
        event = self.factory.inbound_event(self.endpoint, received_at=received)

        event.write({"processed_at": processed})

        self.assertAlmostEqual(event.processing_seconds, 30.0)

    def test_compute_queue_job_count_false_branch_empty_identity_keys(self):
        empty = self.env["bwt.webhook.inbound.event"].browse()
        # Calling on an empty recordset means identity_keys list is empty,
        # exercising the False branch of ``if identity_keys:``.
        empty._compute_queue_job_count()


class TestInboundEventProcessEventDispatchReturnsResult(WebhookTestCase):
    """``process_event`` applies a non-None result from ``_invoke_inbound_dispatch``."""

    def setUp(self):
        super().setUp()
        # Endpoint with no handler so process_event goes through _invoke_inbound_dispatch
        self.endpoint = self.factory.inbound_endpoint()

    def test_process_event_applies_result_from_dispatch(self):
        event = self.factory.inbound_event(self.endpoint)
        self.assertFalse(event.handler_id)

        with patch.object(
            type(event),
            "_invoke_inbound_dispatch",
            return_value={"status": "done", "note": "dispatched"},
        ):
            event.process_event()

        self.assertEqual(event.state, "done")
        self.assertEqual(event.processing_note, "dispatched")
