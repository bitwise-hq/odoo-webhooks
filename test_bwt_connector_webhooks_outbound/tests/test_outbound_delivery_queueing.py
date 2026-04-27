"""Tests for ``queue_outbound_delivery`` and the validation helper."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


def _create_endpoint(env, backend, code, path):
    return env["bwt.webhook.outbound.endpoint"].create(
        {
            "name": code,
            "code": code,
            "http_method": "post",
            "target_hostname": "https://example.com",
            "target_path": path,
            "connector_backend_ref": f"{backend._name},{backend.id}",
        }
    )


class _BackendOutboundTestCase(TransactionCase):
    BACKEND_MODEL = "bwt.test.connector.webhook.backend.outbound"

    def setUp(self):
        super().setUp()
        self.backend = self.env[self.BACKEND_MODEL].create({"name": "Acme", "code": "acme"})
        self.endpoint = _create_endpoint(self.env, self.backend, f"primary-{self.backend.id}", "/primary")


class TestQueueOutboundDelivery(_BackendOutboundTestCase):
    """``queue_outbound_delivery`` creates a delivery and optionally queues it."""

    def test_creates_delivery_record_for_linked_endpoint(self):
        delivery = self.backend.queue_outbound_delivery(
            self.endpoint,
            "test delivery",
            payload={"a": 1},
            headers={"X-Test": "1"},
            auto_queue=False,
        )

        self.assertTrue(delivery.id)
        self.assertEqual(delivery.endpoint_id, self.endpoint)

    def test_context_values_create_context_lines(self):
        delivery = self.backend.queue_outbound_delivery(
            self.endpoint,
            "with context",
            context_values={"binding_id": 42, "extra": {"k": "v"}},
            auto_queue=False,
        )

        lines = self.env["bwt.webhook.outbound.delivery.context.line"].search([("delivery_id", "=", delivery.id)])
        keys = sorted(lines.mapped("key_name"))

        self.assertEqual(keys, ["binding_id", "extra"])


class TestValidateOutboundEndpointForQueue(_BackendOutboundTestCase):
    """``_validate_outbound_endpoint_for_queue`` rejects missing/foreign endpoints."""

    def test_missing_endpoint_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "must be provided"):
            self.backend._validate_outbound_endpoint_for_queue(False)

    def test_endpoint_not_linked_to_backend_is_rejected(self):
        other_backend = self.env[self.BACKEND_MODEL].create({"name": "Other", "code": "other"})
        other_endpoint = _create_endpoint(self.env, other_backend, f"primary-{other_backend.id}", "/primary")

        with self.assertRaisesRegex(ValidationError, "not linked to this connector"):
            self.backend._validate_outbound_endpoint_for_queue(other_endpoint)

    def test_non_outbound_endpoint_record_is_rejected(self):
        partner = self.env["res.partner"].create({"name": "x"})

        with self.assertRaisesRegex(ValidationError, "must be provided"):
            self.backend._validate_outbound_endpoint_for_queue(partner)


class TestQueueOutboundDeliveryAutoQueue(_BackendOutboundTestCase):
    """``queue_outbound_delivery`` with ``auto_queue=True`` calls ``action_queue_delivery``."""

    def test_auto_queue_invokes_action_queue_delivery(self):
        from unittest.mock import patch

        called = []

        def _stub_queue(self_delivery):
            called.append(self_delivery.id)

        delivery_cls = type(self.env["bwt.webhook.outbound.delivery"])
        with patch.object(delivery_cls, "action_queue_delivery", _stub_queue):
            delivery = self.backend.queue_outbound_delivery(
                self.endpoint,
                "auto-queued",
                auto_queue=True,
            )

        self.assertTrue(delivery.id)
        self.assertIn(delivery.id, called)
