"""Behavioral tests for :class:`webhook.outbound.delivery`.

Test suites in this module:

* :class:`TestDeliveryCreateNormalization`
* :class:`TestDeliveryWriteNormalization`
* :class:`TestDeliveryConfigurationConstraint`
* :class:`TestDeliverySnapshotPreparation`
* :class:`TestDeliveryAccessors`
* :class:`TestDeliverySourceValueResolution`
* :class:`TestDeliveryPayloadPathHelper`
* :class:`TestDeliveryRuntimeUserAndIdentity`
* :class:`TestDeliveryQueueJobObservability`
* :class:`TestDeliveryBuildOutboundRequest`
* :class:`TestDeliveryApplyHandlerResult`
* :class:`TestDeliveryQueueProcessing`
* :class:`TestDeliveryResetToDraft`
* :class:`TestDeliveryCancel`
* :class:`TestDeliveryReplay`
* :class:`TestDeliveryAttemptCount`
* :class:`TestDeliveryClassifyResponseStatus`
* :class:`TestDeliveryProcessSkipsTerminalStates`
* :class:`TestDeliveryProcessHandlerOutcomes`
* :class:`TestDeliveryProcessTransport`
* :class:`TestDeliveryProcessRequestBodyModes`
* :class:`TestDeliveryProcessFailureRecording`
"""

from unittest.mock import Mock, patch

import requests

from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.queue_job.exception import RetryableJobError
from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError
from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase

from odoo.addons.bwt_webhooks_outbound.models import (
    webhook_outbound_delivery as outbound_delivery_module,
)
from odoo.addons.bwt_webhooks_core.services.value_objects import (
    HandlerOutcome,
    OutboundRequest,
)


class TestDeliveryCreateNormalization(WebhookTestCase):
    """``create`` normalizes JSON snapshots and rejects malformed input."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.outbound_endpoint()

    def test_create_serializes_typed_header_values_as_strings(self):
        delivery = self.factory.outbound_delivery(
            self.endpoint,
            request_headers_json='{"X-Count": 7, "X-Enabled": true}',
        )

        self.assertEqual(delivery._get_request_headers(), {"X-Count": "7", "X-Enabled": "True"})

    def test_create_preserves_typed_payload_values(self):
        delivery = self.factory.outbound_delivery(
            self.endpoint,
            payload_json='{"amount": 12, "items": [1, 2]}',
        )

        self.assertEqual(delivery._get_payload(), {"amount": 12, "items": [1, 2]})

    def test_create_rejects_invalid_headers_json(self):
        with self.assertRaisesRegex(ValidationError, "must be valid JSON"):
            self.factory.outbound_delivery(self.endpoint, request_headers_json="{broken")

    def test_create_rejects_non_object_headers_json(self):
        with self.assertRaisesRegex(ValidationError, "must be a JSON object"):
            self.factory.outbound_delivery(self.endpoint, request_headers_json="[]")

    def test_create_rejects_invalid_payload_json(self):
        with self.assertRaisesRegex(ValidationError, "must be valid JSON"):
            self.factory.outbound_delivery(self.endpoint, payload_json="{broken")


class TestDeliveryWriteNormalization(WebhookTestCase):
    """``write`` re-normalizes JSON snapshots in place."""

    def test_write_renormalizes_headers_and_payload(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)

        delivery.write(
            {
                "request_headers_json": '{"X-Mode": "live", "X-Int": 9}',
                "payload_json": '{"nested": {"ok": true}}',
            }
        )

        self.assertEqual(delivery._get_request_headers(), {"X-Int": "9", "X-Mode": "live"})
        self.assertEqual(delivery._get_payload(), {"nested": {"ok": True}})


class TestDeliveryConfigurationConstraint(WebhookTestCase):
    """``_check_delivery_configuration`` requires a target url and positive timeout."""

    def test_endpoint_with_zero_timeout_propagates_validation_error(self):
        endpoint = self.factory.outbound_endpoint()
        endpoint.invalidate_recordset()

        with self.assertRaisesRegex(ValidationError, "greater than zero seconds"):
            endpoint.write({"timeout_seconds": 0})


class TestDeliverySnapshotPreparation(WebhookTestCase):
    """``_prepare_endpoint_snapshot_vals`` fills runtime defaults."""

    def test_snapshot_vals_default_empty_snapshots(self):
        endpoint = self.factory.outbound_endpoint()

        vals = self.env["bwt.webhook.outbound.delivery"]._prepare_endpoint_snapshot_vals(endpoint, {})

        self.assertEqual(vals["request_headers_json"], "{}")
        self.assertEqual(vals["payload_json"], "{}")
        self.assertTrue(vals["name"].startswith(f"{endpoint.display_name} / "))


class TestDeliveryAccessors(WebhookTestCase):
    """``_get_request_headers`` / ``_get_payload`` parse stored JSON snapshots."""

    def test_invalid_headers_raise_configuration_error_on_read(self):
        invalid = self.env["bwt.webhook.outbound.delivery"].new({"request_headers_json": "{broken", "payload_json": "{}"})

        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "Request Headers must be valid JSON"):
            invalid._get_request_headers()

    def test_invalid_payload_raises_configuration_error_on_read(self):
        invalid = self.env["bwt.webhook.outbound.delivery"].new({"request_headers_json": "{}", "payload_json": "{broken"})

        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "Payload JSON must be valid JSON"):
            invalid._get_payload()


class TestDeliverySourceValueResolution(WebhookTestCase):
    """``_resolve_source_value`` and ``_resolve_expression_value`` cover every source kind."""

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({"name": "Tenant Partner", "is_company": True})
        self.endpoint = self.factory.outbound_endpoint()
        self.delivery = self.factory.outbound_delivery(self.endpoint)

    def test_literal_source_decodes_quoted_string(self):
        self.assertEqual(
            self.delivery._resolve_source_value("literal", literal_value='"trace-001"'),
            "trace-001",
        )

    def test_endpoint_field_source_resolves_endpoint_attribute(self):
        self.assertEqual(
            self.delivery._resolve_source_value("endpoint_field", "code"),
            self.endpoint.code,
        )

    def test_company_field_source_resolves_company_attribute(self):
        self.assertEqual(
            self.delivery._resolve_source_value("company_field", "name"),
            self.delivery.company_id.name,
        )

    def test_request_field_source_resolves_dotted_path(self):
        self.assertEqual(
            self.delivery._resolve_source_value(
                "request_field",
                "payload.meta.trace",
                request_data={"payload": {"meta": {"trace": "abc"}}},
            ),
            "abc",
        )

    def test_unsupported_source_kind_returns_falsy(self):
        self.assertFalse(self.delivery._resolve_source_value("unsupported", "code"))

    def test_blank_expression_returns_falsy(self):
        self.assertFalse(self.delivery._resolve_source_value("request_field", False))

    def test_unresolvable_expression_raises_configuration_error(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "missing.attribute"):
            self.delivery._resolve_source_value("endpoint_field", "missing.attribute")

    def test_resolve_expression_value_walks_dict_path(self):
        self.assertEqual(
            self.delivery._resolve_expression_value({"meta": {"code": 9}}, "meta.code"),
            9,
        )

    def test_resolve_expression_value_returns_recordset_ids_for_multi(self):
        partners = self.env["res.partner"].browse([self.partner.id, self.delivery.company_id.partner_id.id])

        self.assertEqual(
            self.delivery._resolve_expression_value(partners, ""),
            partners.ids,
        )


class TestDeliveryPayloadPathHelper(WebhookTestCase):
    """``_set_payload_path`` writes nested values and rejects collisions."""

    def setUp(self):
        super().setUp()
        self.delivery_model = self.env["bwt.webhook.outbound.delivery"]

    def test_nested_path_creates_intermediate_objects(self):
        self.assertEqual(
            self.delivery_model._set_payload_path({}, "meta.trace", "abc"),
            {"meta": {"trace": "abc"}},
        )

    def test_blank_path_with_dict_value_replaces_payload(self):
        self.assertEqual(
            self.delivery_model._set_payload_path(False, "", {"ok": True}),
            {"ok": True},
        )

    def test_non_object_payload_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "JSON object payload"):
            self.delivery_model._set_payload_path([], "meta.trace", "abc")

    def test_collision_with_non_object_path_is_rejected(self):
        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "collides with a non-object value"):
            self.delivery_model._set_payload_path({"meta": "value"}, "meta.trace", "abc")


class TestDeliveryCoerceOutboundRequest(WebhookTestCase):
    """``_coerce_outbound_request`` passes through an existing ``OutboundRequest``."""

    def test_passes_through_outbound_request_instance(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)
        existing = OutboundRequest(
            target_url="https://api.example.com/",
            http_method="post",
            request_body_mode="json",
            headers={},
            payload={},
            files={},
        )

        result = delivery._coerce_outbound_request(existing)

        self.assertIs(result, existing)


class TestDeliveryQueueJobIdentity(WebhookTestCase):
    """Queue-job identity helpers."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.outbound_endpoint()
        self.delivery = self.factory.outbound_delivery(self.endpoint)

    def test_queue_job_identity_key_includes_delivery_id(self):
        self.assertEqual(
            self.delivery._get_queue_job_identity_key(),
            f"webhook_outbound_delivery_process:{self.delivery.id}",
        )

    def test_queue_job_action_domain_targets_process_delivery_method(self):
        self.assertEqual(
            self.delivery._get_queue_job_action_domain(),
            [
                (
                    "identity_key",
                    "=",
                    f"webhook_outbound_delivery_process:{self.delivery.id}",
                ),
                ("model_name", "=", "bwt.webhook.outbound.delivery"),
                ("method_name", "=", "process_delivery"),
            ],
        )

    def test_action_view_queue_jobs_uses_outbound_label_and_domain(self):
        action = self.delivery.action_view_queue_jobs()

        self.assertEqual(action["name"], "Outbound Queue Jobs")
        self.assertEqual(action["domain"], self.delivery._get_queue_job_action_domain())

    def test_queue_job_action_domain_without_identity_key_excludes_all(self):
        self.delivery.queue_job_identity_key = False

        self.assertEqual(self.delivery._get_queue_job_action_domain(), [("id", "=", 0)])


class TestDeliveryQueueJobObservability(WebhookTestCase):
    """``_compute_queue_job_observability`` reports the latest queued job state."""

    def test_delivery_without_queue_jobs_reports_zero_count(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)

        delivery._compute_queue_job_identity_key()
        delivery._compute_queue_job_observability()

        self.assertFalse(delivery.queue_job_ids)
        self.assertEqual(delivery.queue_job_count, 0)
        self.assertFalse(delivery.latest_queue_job_id)
        self.assertFalse(delivery.latest_queue_job_state)

    def test_compute_on_empty_recordset_does_not_search_jobs(self):
        empty = self.env["bwt.webhook.outbound.delivery"].browse([])

        empty._compute_queue_job_observability()

    def test_delivery_with_queue_jobs_aggregates_count_and_latest_state(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)
        identity_key = delivery.queue_job_identity_key
        self.assertTrue(identity_key)
        job_a = self.env["queue.job"].create(
            {
                "uuid": "out-job-a-%s" % delivery.id,
                "identity_key": identity_key,
                "model_name": "bwt.webhook.outbound.delivery",
                "method_name": "process_delivery",
                "state": "done",
                "func_string": "d.process_delivery()",
            }
        )
        job_b = self.env["queue.job"].create(
            {
                "uuid": "out-job-b-%s" % delivery.id,
                "identity_key": identity_key,
                "model_name": "bwt.webhook.outbound.delivery",
                "method_name": "process_delivery",
                "state": "pending",
                "func_string": "d.process_delivery()",
            }
        )

        delivery.invalidate_recordset()

        self.assertEqual(delivery.queue_job_count, 2)
        self.assertEqual(delivery.queue_job_ids, job_a | job_b)
        self.assertIn(delivery.latest_queue_job_state, ("done", "pending"))


class TestDeliveryBuildOutboundRequest(WebhookTestCase):
    """``_build_outbound_request`` merges base snapshots, header rules and payload rules."""

    def test_request_target_url_reflects_current_endpoint_target_url(self):
        endpoint = self.factory.outbound_endpoint(target_hostname="https://example.com", target_path="/original")
        delivery = self.factory.outbound_delivery(endpoint)

        endpoint.write(
            {
                "target_hostname": "https://override.example.com",
                "target_path": "/hooks/orders",
            }
        )

        request = delivery._build_outbound_request()

        self.assertEqual(request.target_url, "https://override.example.com/hooks/orders")

    def test_datetime_payload_value_is_stringified(self):
        endpoint = self.factory.outbound_endpoint()
        self.factory.outbound_payload_rule(
            endpoint,
            target_path="meta.created_at",
            source_kind="delivery_field",
            source_expression="create_date",
        )
        delivery = self.factory.outbound_delivery(endpoint)

        request = delivery._build_outbound_request()

        self.assertEqual(
            request.payload["meta"]["created_at"],
            fields.Datetime.to_string(delivery.create_date),
        )


class TestDeliveryApplyHandlerResult(WebhookTestCase):
    """``_apply_handler_result`` interprets raw handler return values."""

    def setUp(self):
        super().setUp()
        endpoint = self.factory.outbound_endpoint()
        self.delivery = self.factory.outbound_delivery(endpoint)
        self.base_request = {
            "target_url": self.delivery.target_url,
            "http_method": "post",
            "request_body_mode": "json",
            "headers": {"X-Test": "1"},
            "payload": {"meta": {"ok": True}},
            "files": {},
        }

    def test_truthy_non_dict_result_leaves_request_unchanged(self):
        result, updated = self.delivery._apply_handler_result(True, self.base_request)

        self.assertTrue(result)
        self.assertEqual(updated, self.base_request)

    def test_dict_result_overrides_target_url_and_http_method(self):
        _, updated = self.delivery._apply_handler_result(
            {
                "status": "send",
                "target_url": "https://override.example.com/out",
                "http_method": "PATCH",
            },
            self.base_request,
        )

        self.assertEqual(updated["target_url"], "https://override.example.com/out")
        self.assertEqual(updated["http_method"], "patch")

    def test_dict_result_replaces_headers_and_payload(self):
        _, updated = self.delivery._apply_handler_result(
            {
                "status": "send",
                "headers": {"X-Number": 5},
                "payload": {"meta": {"count": 2}},
            },
            self.base_request,
        )

        self.assertEqual(updated["headers"], {"X-Number": "5"})
        self.assertEqual(updated["payload"], {"meta": {"count": 2}})

    def test_transport_mode_alias_updates_request_body_mode(self):
        _, updated = self.delivery._apply_handler_result({"status": "send", "transport_mode": "form_urlencoded"}, self.base_request)

        self.assertEqual(updated["request_body_mode"], "form_urlencoded")


class TestDeliveryQueueProcessing(WebhookTestCase):
    """``_queue_processing`` enqueues a process_delivery job for queueable deliveries."""

    def test_draft_endpoint_blocks_queueing(self):
        endpoint = self.factory.outbound_endpoint(state="draft")
        delivery = self.factory.outbound_delivery(endpoint)

        with self.assertRaisesRegex(ValidationError, "Draft outbound endpoint"):
            delivery._queue_processing()

    def test_archived_endpoint_blocks_queueing(self):
        endpoint = self.factory.outbound_endpoint(state="archived")
        delivery = self.factory.outbound_delivery(endpoint)

        with self.assertRaisesRegex(ValidationError, "Archived outbound endpoint"):
            delivery._queue_processing()

    def test_queued_delivery_cannot_be_queued_again(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint, state="queued")

        with self.assertRaisesRegex(ValidationError, "Only draft or failed deliveries can be queued"):
            delivery.action_queue_delivery()

    def test_failed_delivery_can_be_requeued(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint, state="error")
        delayed = Mock()

        with patch.object(type(delivery), "with_user", autospec=True, return_value=delivery):
            with patch.object(type(delivery), "with_delay", autospec=True, return_value=delayed) as with_delay_mock:
                self.assertTrue(delivery.action_queue_delivery())

        self.assertEqual(delivery.state, "queued")
        self.assertTrue(delivery.queued_at)
        self.assertFalse(delivery.processing_error)
        with_delay_mock.assert_called_once_with(
            delivery,
            identity_key=f"webhook_outbound_delivery_process:{delivery.id}",
        )
        delayed.process_delivery.assert_called_once_with()


class TestDeliveryResetToDraft(WebhookTestCase):
    """``action_reset_to_draft`` clears audit fields on resettable deliveries."""

    def test_done_delivery_cannot_be_reset(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint, state="done")

        with self.assertRaisesRegex(ValidationError, "Only failed, dead-letter, or canceled"):
            delivery.action_reset_to_draft()

    def test_failed_delivery_reset_clears_audit_fields(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(
            endpoint,
            state="error",
            response_status_code=500,
            response_headers_json='{"X-Test": "1"}',
            response_body="boom",
            processing_note="bad",
            processing_error="trace",
            queued_at=fields.Datetime.now(),
            processed_at=fields.Datetime.now(),
        )

        delivery.action_reset_to_draft()

        self.assertEqual(delivery.state, "draft")
        self.assertFalse(delivery.queued_at)
        self.assertFalse(delivery.processed_at)
        self.assertFalse(delivery.processing_note)
        self.assertFalse(delivery.processing_error)
        self.assertFalse(delivery.response_status_code)
        self.assertFalse(delivery.response_body)


class TestDeliveryCancel(WebhookTestCase):
    """``action_cancel_delivery`` cancels only draft or failed deliveries."""

    def test_queued_delivery_cannot_be_canceled(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint, state="queued")

        with self.assertRaisesRegex(ValidationError, "Only draft or failed deliveries"):
            delivery.action_cancel_delivery()

    def test_draft_delivery_can_be_canceled(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint, state="draft")

        delivery.action_cancel_delivery()

        self.assertEqual(delivery.state, "canceled")


class TestDeliveryReplay(WebhookTestCase):
    """``action_create_replay_delivery`` produces audited replays."""

    def setUp(self):
        super().setUp()
        endpoint = self.factory.outbound_endpoint()
        self.delivery = self.factory.outbound_delivery(endpoint, state="done")

    def test_replay_links_back_to_source_delivery(self):
        action = self.delivery.action_create_replay_delivery()
        replay = self.env["bwt.webhook.outbound.delivery"].browse(action["res_id"])

        self.assertEqual(replay.replayed_from_delivery_id, self.delivery)

    def test_replays_are_numbered_sequentially(self):
        first = self.env["bwt.webhook.outbound.delivery"].browse(self.delivery.action_create_replay_delivery()["res_id"])
        second = self.env["bwt.webhook.outbound.delivery"].browse(self.delivery.action_create_replay_delivery()["res_id"])

        self.assertTrue(first.name.endswith("Replay 1"))
        self.assertTrue(second.name.endswith("Replay 2"))

    def test_replay_count_compute_reflects_replay_records(self):
        self.delivery.action_create_replay_delivery()
        self.delivery.action_create_replay_delivery()

        self.delivery.invalidate_recordset(["replay_delivery_ids", "replay_count"])

        self.assertEqual(self.delivery.replay_count, 2)

    def test_queued_delivery_cannot_be_replayed(self):
        endpoint = self.factory.outbound_endpoint()
        queued = self.factory.outbound_delivery(endpoint, state="queued")

        with self.assertRaisesRegex(ValidationError, "cannot be replayed"):
            queued.action_create_replay_delivery()


class TestDeliveryAttemptCount(WebhookTestCase):
    """``_compute_attempt_count`` mirrors ``attempt_ids``."""

    def test_attempt_count_increments_with_each_attempt(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)
        self.factory.outbound_attempt(delivery, attempt_number=1)
        self.factory.outbound_attempt(delivery, attempt_number=2)

        delivery.invalidate_recordset(["attempt_ids", "attempt_count"])

        self.assertEqual(delivery.attempt_count, 2)


class TestDeliveryClassifyResponseStatus(WebhookTestCase):
    """``_classify_response_status`` maps HTTP codes to delivery states."""

    def test_2xx_is_classified_as_done(self):
        self.assertEqual(
            self.env["bwt.webhook.outbound.delivery"]._classify_response_status(202),
            "done",
        )

    def test_3xx_is_classified_as_done(self):
        self.assertEqual(
            self.env["bwt.webhook.outbound.delivery"]._classify_response_status(301),
            "done",
        )

    def test_4xx_is_classified_as_dead_letter(self):
        self.assertEqual(
            self.env["bwt.webhook.outbound.delivery"]._classify_response_status(422),
            "dead_letter",
        )

    def test_5xx_is_classified_as_error(self):
        self.assertEqual(
            self.env["bwt.webhook.outbound.delivery"]._classify_response_status(503),
            "error",
        )


class TestDeliveryProcessSkipsTerminalStates(WebhookTestCase):
    """``process_delivery`` short-circuits on terminal delivery states."""

    def test_done_delivery_is_not_dispatched(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint, state="done")

        with patch.object(outbound_delivery_module.requests, "request") as request_mock:
            delivery.process_delivery()

        request_mock.assert_not_called()


class TestDeliveryProcessHandlerOutcomes(WebhookTestCase):
    """``process_delivery`` honours handler-driven cancel / dead_letter / retry / send."""

    def _delivery_with_handler(self):
        handler = self.factory.handler(direction="outbound")
        endpoint = self.factory.outbound_endpoint(handler=handler)
        return handler, self.factory.outbound_delivery(endpoint)

    def test_handler_cancel_marks_delivery_canceled_without_dispatch(self):
        handler, delivery = self._delivery_with_handler()

        with patch.object(
            type(handler),
            "execute_outbound",
            autospec=True,
            return_value={"status": "cancel", "note": "Canceled by handler"},
        ):
            with patch.object(outbound_delivery_module.requests, "request") as request_mock:
                delivery.process_delivery()

        self.assertEqual(delivery.state, "canceled")
        self.assertEqual(delivery.attempt_ids[:1].state, "canceled")
        request_mock.assert_not_called()

    def test_handler_dead_letter_marks_delivery_dead_letter_without_dispatch(self):
        handler, delivery = self._delivery_with_handler()

        with patch.object(
            type(handler),
            "execute_outbound",
            autospec=True,
            return_value={"status": "dead_letter", "note": "Blocked by handler"},
        ):
            with patch.object(outbound_delivery_module.requests, "request") as request_mock:
                delivery.process_delivery()

        self.assertEqual(delivery.state, "dead_letter")
        self.assertEqual(delivery.processing_note, "Blocked by handler")
        request_mock.assert_not_called()

    def test_handler_retry_raises_retryable_job_error_and_records_error(self):
        handler, delivery = self._delivery_with_handler()

        with patch.object(
            type(handler),
            "execute_outbound",
            autospec=True,
            return_value={
                "status": "retry",
                "note": "Retry by handler",
                "seconds": 12,
            },
        ):
            with patch.object(outbound_delivery_module.requests, "request") as request_mock:
                with self.assertRaisesRegex(RetryableJobError, "Retry by handler"):
                    delivery.process_delivery()

        self.assertEqual(delivery.state, "error")
        self.assertEqual(delivery.attempt_ids[:1].state, "error")
        request_mock.assert_not_called()

    def test_handler_returning_false_cancels_delivery(self):
        handler, delivery = self._delivery_with_handler()

        with patch.object(type(handler), "execute_outbound", autospec=True, return_value=False):
            with patch.object(outbound_delivery_module.requests, "request") as request_mock:
                delivery.process_delivery()

        self.assertEqual(delivery.state, "canceled")
        request_mock.assert_not_called()


class TestDeliveryProcessTransport(WebhookTestCase):
    """``_dispatch`` and ``_record_response`` translate transport outcomes."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.outbound_endpoint()

    def test_2xx_response_marks_delivery_done(self):
        delivery = self.factory.outbound_delivery(self.endpoint)

        with patch.object(
            outbound_delivery_module.requests,
            "request",
            return_value=Mock(status_code=202, headers={"X-Reply": "yes"}, text="ok"),
        ):
            delivery.process_delivery()

        self.assertEqual(delivery.state, "done")
        self.assertEqual(delivery.response_status_code, 202)
        self.assertEqual(delivery.attempt_ids[:1].state, "done")

    def test_4xx_response_marks_delivery_dead_letter(self):
        delivery = self.factory.outbound_delivery(self.endpoint)

        with patch.object(
            outbound_delivery_module.requests,
            "request",
            return_value=Mock(status_code=422, headers={}, text="invalid"),
        ):
            delivery.process_delivery()

        self.assertEqual(delivery.state, "dead_letter")
        self.assertIn("HTTP 422", delivery.processing_error)

    def test_5xx_response_raises_retryable_and_records_error(self):
        delivery = self.factory.outbound_delivery(self.endpoint)

        with patch.object(
            outbound_delivery_module.requests,
            "request",
            return_value=Mock(status_code=503, headers={}, text="busy"),
        ):
            with self.assertRaisesRegex(RetryableJobError, "HTTP 503"):
                delivery.process_delivery()

        self.assertEqual(delivery.state, "error")

    def test_request_exception_raises_retryable_and_records_error(self):
        delivery = self.factory.outbound_delivery(self.endpoint)

        with patch.object(
            outbound_delivery_module.requests,
            "request",
            side_effect=requests.RequestException("network down"),
        ):
            with self.assertRaisesRegex(RetryableJobError, "network down"):
                delivery.process_delivery()

        self.assertEqual(delivery.state, "error")
        self.assertIn("network down", delivery.processing_error)


class TestDeliveryProcessRequestBodyModes(WebhookTestCase):
    """``process_delivery`` chooses the right transport kwargs for each body mode."""

    def test_json_mode_sends_json_kwarg(self):
        endpoint = self.factory.outbound_endpoint(request_body_mode="json")
        delivery = self.factory.outbound_delivery(endpoint, payload_json='{"event": "created"}')

        with patch.object(
            outbound_delivery_module.requests,
            "request",
            return_value=Mock(status_code=200, headers={}, text="ok"),
        ) as request_mock:
            delivery.process_delivery()

        kwargs = request_mock.call_args.kwargs
        self.assertEqual(kwargs["json"], {"event": "created"})
        self.assertNotIn("data", kwargs)
        self.assertNotIn("files", kwargs)

    def test_form_urlencoded_mode_sends_flattened_data_kwarg(self):
        endpoint = self.factory.outbound_endpoint(request_body_mode="form_urlencoded")
        self.factory.outbound_payload_rule(endpoint, target_path="meta.enabled", literal_value="true")
        self.factory.outbound_payload_rule(endpoint, target_path="meta.count", literal_value="2")
        delivery = self.factory.outbound_delivery(endpoint)

        with patch.object(
            outbound_delivery_module.requests,
            "request",
            return_value=Mock(status_code=200, headers={}, text="ok"),
        ) as request_mock:
            delivery.process_delivery()

        kwargs = request_mock.call_args.kwargs
        self.assertEqual(kwargs["data"], {"meta[count]": "2", "meta[enabled]": "true"})
        self.assertNotIn("json", kwargs)
        self.assertNotIn("files", kwargs)

    def test_multipart_mode_sends_data_and_files_kwargs(self):
        handler = self.factory.handler(direction="outbound")
        endpoint = self.factory.outbound_endpoint(handler=handler, request_body_mode="json")
        delivery = self.factory.outbound_delivery(endpoint)

        with patch.object(
            type(handler),
            "execute_outbound",
            autospec=True,
            return_value={
                "status": "send",
                "request_body_mode": "multipart",
                "payload": {"meta": {"tag": "invoice"}},
                "files": {"invoice": ("invoice.txt", "body", "text/plain")},
            },
        ):
            with patch.object(
                outbound_delivery_module.requests,
                "request",
                return_value=Mock(status_code=200, headers={}, text="ok"),
            ) as request_mock:
                delivery.process_delivery()

        kwargs = request_mock.call_args.kwargs
        self.assertEqual(kwargs["data"], {"meta[tag]": "invoice"})
        self.assertIn("invoice", kwargs["files"])
        self.assertEqual(delivery.attempt_ids[:1].request_body_mode, "multipart")
        self.assertEqual(delivery.attempt_ids[:1].multipart_file_keys, "invoice")

    def test_files_without_multipart_mode_are_rejected(self):
        handler = self.factory.handler(direction="outbound")
        endpoint = self.factory.outbound_endpoint(handler=handler, request_body_mode="json")
        delivery = self.factory.outbound_delivery(endpoint)

        with patch.object(
            type(handler),
            "execute_outbound",
            autospec=True,
            return_value={
                "status": "send",
                "files": {"invoice": ("invoice.txt", "body")},
            },
        ):
            with self.assertRaisesRegex(
                WebhookProcessingConfigurationError,
                "cannot include multipart files",
            ):
                delivery.process_delivery()

        self.assertEqual(delivery.state, "error")


class TestDeliveryProcessFailureRecording(WebhookTestCase):
    """``_record_pre_dispatch_failure`` audits exceptions raised before dispatch."""

    def test_attempt_logging_failure_is_captured_in_processing_error(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)

        with patch.object(
            type(delivery),
            "_create_attempt",
            autospec=True,
            side_effect=RuntimeError("attempt logging failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "attempt logging failed"):
                delivery.process_delivery()

        self.assertEqual(delivery.state, "error")
        self.assertIn("attempt logging failed", delivery.processing_error)

    def test_request_build_failure_records_error_without_attempt(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)

        with patch.object(
            type(delivery),
            "_build_outbound_request",
            autospec=True,
            side_effect=RuntimeError("cannot build request"),
        ):
            with self.assertRaisesRegex(RuntimeError, "cannot build request"):
                delivery.process_delivery()

        self.assertEqual(delivery.state, "error")
        self.assertIn("cannot build request", delivery.processing_error)
        self.assertFalse(delivery.attempt_ids)


class TestDeliveryHandleOutboundResponseHook(WebhookTestCase):
    """``_handle_outbound_response`` fires after the framework records the HTTP outcome."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.outbound_endpoint()

    def test_default_implementation_is_noop(self):
        delivery = self.factory.outbound_delivery(self.endpoint)
        outcome = HandlerOutcome(status="send", request=OutboundRequest.from_dict({}))
        # Should not raise and should not mutate state.
        self.assertIsNone(delivery._handle_outbound_response(Mock(status_code=200), "done", outcome))

    def test_hook_fires_once_on_success_with_done_state(self):
        delivery = self.factory.outbound_delivery(self.endpoint)
        calls = []

        def _capture(self, response, state, outcome):
            calls.append((self.id, response.status_code, state, outcome))

        with patch.object(
            outbound_delivery_module.requests,
            "request",
            return_value=Mock(status_code=200, headers={}, text="ok"),
        ):
            with patch.object(
                type(delivery),
                "_handle_outbound_response",
                _capture,
            ):
                delivery.process_delivery()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], delivery.id)
        self.assertEqual(calls[0][1], 200)
        self.assertEqual(calls[0][2], "done")
        self.assertEqual(delivery.state, "done")

    def test_hook_fires_on_dead_letter_state(self):
        delivery = self.factory.outbound_delivery(self.endpoint)
        calls = []

        def _capture(self, response, state, outcome):
            calls.append(state)

        with patch.object(
            outbound_delivery_module.requests,
            "request",
            return_value=Mock(status_code=422, headers={}, text="bad"),
        ):
            with patch.object(
                type(delivery),
                "_handle_outbound_response",
                _capture,
            ):
                delivery.process_delivery()

        self.assertEqual(calls, ["dead_letter"])

    def test_hook_fires_before_retryable_raise_on_error_state(self):
        delivery = self.factory.outbound_delivery(self.endpoint)
        calls = []

        def _capture(self, response, state, outcome):
            calls.append((state, self.state))

        with patch.object(
            outbound_delivery_module.requests,
            "request",
            return_value=Mock(status_code=503, headers={}, text="busy"),
        ):
            with patch.object(
                type(delivery),
                "_handle_outbound_response",
                _capture,
            ):
                with self.assertRaises(RetryableJobError):
                    delivery.process_delivery()

        self.assertEqual(len(calls), 1)
        # State 'error' is already written on the delivery before the hook fires.
        self.assertEqual(calls[0], ("error", "error"))


class TestDeliveryLatencySeconds(WebhookTestCase):
    """``_compute_latency_seconds`` derives queue_to_done_seconds and end_to_end_seconds."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.outbound_endpoint()

    def test_both_fields_are_zero_when_not_yet_processed(self):
        delivery = self.factory.outbound_delivery(self.endpoint)

        self.assertEqual(delivery.queue_to_done_seconds, 0.0)
        self.assertEqual(delivery.end_to_end_seconds, 0.0)

    def test_end_to_end_seconds_uses_create_date_to_processed_at(self):
        processed = fields.Datetime.from_string("2026-01-01 12:00:45")
        delivery = self.factory.outbound_delivery(self.endpoint, processed_at=processed)
        # create_date is set by Odoo; simulate a 45-second window.
        delivery.write({"create_date": fields.Datetime.from_string("2026-01-01 12:00:00")})

        delivery.invalidate_recordset(["end_to_end_seconds", "queue_to_done_seconds"])
        delivery._compute_latency_seconds()

        self.assertGreater(delivery.end_to_end_seconds, 0.0)

    def test_queue_to_done_seconds_uses_queued_at_to_processed_at(self):
        queued = fields.Datetime.from_string("2026-01-01 12:00:00")
        processed = fields.Datetime.from_string("2026-01-01 12:00:20")
        delivery = self.factory.outbound_delivery(
            self.endpoint,
            queued_at=queued,
            processed_at=processed,
        )

        delivery.invalidate_recordset(["queue_to_done_seconds"])
        delivery._compute_latency_seconds()

        self.assertAlmostEqual(delivery.queue_to_done_seconds, 20.0)

    def test_queue_to_done_is_zero_when_queued_at_absent(self):
        processed = fields.Datetime.from_string("2026-01-01 12:00:30")
        delivery = self.factory.outbound_delivery(self.endpoint, processed_at=processed)

        delivery.invalidate_recordset(["queue_to_done_seconds"])
        delivery._compute_latency_seconds()

        self.assertEqual(delivery.queue_to_done_seconds, 0.0)

    def test_latency_floored_at_zero_when_timestamps_inverted(self):
        queued = fields.Datetime.from_string("2026-01-01 12:00:30")
        processed = fields.Datetime.from_string("2026-01-01 12:00:00")
        delivery = self.factory.outbound_delivery(
            self.endpoint,
            queued_at=queued,
            processed_at=processed,
        )

        delivery.invalidate_recordset(["queue_to_done_seconds"])
        delivery._compute_latency_seconds()

        self.assertEqual(delivery.queue_to_done_seconds, 0.0)

    def test_latency_true_branches_via_write_processed_at(self):
        from datetime import timedelta

        now = fields.Datetime.now()
        queued = now - timedelta(seconds=20)
        processed = now + timedelta(seconds=30)
        delivery = self.factory.outbound_delivery(self.endpoint, queued_at=queued)

        delivery.write({"processed_at": processed})

        self.assertGreater(delivery.queue_to_done_seconds, 0.0)
        self.assertGreater(delivery.end_to_end_seconds, 0.0)
