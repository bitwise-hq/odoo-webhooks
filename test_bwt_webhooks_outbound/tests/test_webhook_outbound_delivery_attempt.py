"""Behavioral tests for :class:`webhook.outbound.delivery.attempt`.

Test suites in this module:

* :class:`TestOutboundAttemptCreation`
* :class:`TestOutboundAttemptUniquenessConstraint`
* :class:`TestOutboundAttemptResponseAuditVals`
"""

from types import SimpleNamespace

from psycopg2 import errors as pg_errors

from odoo.tools import mute_logger

from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestOutboundAttemptCreation(WebhookTestCase):
    """``_create_attempt`` records the request snapshot and number-by-position."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.outbound_endpoint()
        self.delivery = self.factory.outbound_delivery(self.endpoint)
        self.request_dict = {
            "http_method": "post",
            "target_url": self.delivery.target_url,
            "headers": {"X-Test": "1"},
            "payload": {"ok": True},
        }

    def test_first_attempt_gets_number_one(self):
        attempt = self.delivery._create_attempt(self.request_dict)

        self.assertEqual(attempt.attempt_number, 1)

    def test_second_attempt_increments_attempt_number(self):
        self.delivery._create_attempt(self.request_dict)

        second = self.delivery._create_attempt(self.request_dict)

        self.assertEqual(second.attempt_number, 2)

    def test_processing_attempt_has_no_finished_at(self):
        attempt = self.delivery._create_attempt(self.request_dict)

        self.assertEqual(attempt.state, "processing")
        self.assertFalse(attempt.finished_at)

    def test_terminal_attempt_records_finished_at(self):
        attempt = self.delivery._create_attempt(self.request_dict, state="done", response_status_code=200)

        self.assertTrue(attempt.finished_at)

    def test_attempt_records_response_audit_fields(self):
        attempt = self.delivery._create_attempt(
            self.request_dict,
            state="done",
            response_status_code=202,
            response_headers={"X-Reply": "yes"},
            response_body="accepted",
        )

        self.assertEqual(attempt.response_status_code, 202)
        self.assertEqual(attempt.response_body, "accepted")
        self.assertIn("X-Reply", attempt.response_headers_json)

    def test_attempt_count_compute_reflects_attempt_records(self):
        self.delivery._create_attempt(self.request_dict)
        self.delivery._create_attempt(self.request_dict, state="done")

        self.delivery.invalidate_recordset(["attempt_ids", "attempt_count"])

        self.assertEqual(self.delivery.attempt_count, 2)

    def test_attempt_inherits_endpoint_and_company_from_delivery(self):
        attempt = self.delivery._create_attempt(self.request_dict)

        self.assertEqual(attempt.endpoint_id, self.endpoint)
        self.assertEqual(attempt.company_id, self.delivery.company_id)


class TestOutboundAttemptUniquenessConstraint(WebhookTestCase):
    """``_delivery_attempt_number_uniq`` prevents duplicate attempt numbers."""

    @mute_logger("odoo.sql_db")
    def test_duplicate_attempt_number_within_delivery_is_rejected(self):
        endpoint = self.factory.outbound_endpoint()
        delivery = self.factory.outbound_delivery(endpoint)
        self.factory.outbound_attempt(delivery, attempt_number=1)

        with self.assertRaises(Exception) as cm:
            with self.env.cr.savepoint():
                self.factory.outbound_attempt(delivery, attempt_number=1)
                delivery.flush_recordset()
        self.assertIsInstance(cm.exception.__cause__ or cm.exception, pg_errors.UniqueViolation)


class TestOutboundAttemptResponseAuditVals(WebhookTestCase):
    """``_response_audit_vals`` packages a :class:`requests.Response`-like object."""

    def test_audit_vals_serialize_status_headers_and_body(self):
        response = SimpleNamespace(
            status_code=502,
            headers={"X-Trace": "abc"},
            text="Bad Gateway",
        )

        audit = self.env["bwt.webhook.outbound.delivery"]._response_audit_vals(response, state="error", note="boom", error_message="HTTP 502")

        self.assertEqual(audit["state"], "error")
        self.assertEqual(audit["response_status_code"], 502)
        self.assertEqual(audit["response_body"], "Bad Gateway")
        self.assertEqual(audit["processing_note"], "boom")
        self.assertEqual(audit["processing_error"], "HTTP 502")
        self.assertIn("X-Trace", audit["response_headers_json"])
