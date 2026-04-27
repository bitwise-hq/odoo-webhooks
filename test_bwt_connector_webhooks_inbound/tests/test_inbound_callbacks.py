"""Tests for the connector-aware inbound dispatch override.

The connector inbound overlay routes ``bwt.webhook.inbound.event``
processing directly to the linked backend's
``_handle_inbound_webhook_event`` when the endpoint has no
``handler_id`` configured, removing the historical
``bwt.webhook.handler`` proxy step.
"""

import hashlib

from odoo.tests.common import TransactionCase


class _BackendInboundTestCase(TransactionCase):
    BACKEND_MODEL = "bwt.test.connector.webhook.backend.inbound"
    BARE_BACKEND_MODEL = "bwt.test.connector.webhook.backend.inbound.bare"

    def setUp(self):
        super().setUp()
        self.backend = self.env[self.BACKEND_MODEL].create({"name": "Acme", "code": "acme"})
        self.endpoint = self.env["bwt.webhook.inbound.endpoint"].create(
            {
                "name": "Test Inbound Endpoint",
                "path": f"test-inbound-{self.backend.id}",
                "delivery_identity_policy": "body_sha256",
                "connector_backend_ref": f"{self.BACKEND_MODEL},{self.backend.id}",
            }
        )

    def _create_event(self, endpoint, body=b"{}"):
        return self.env["bwt.webhook.inbound.event"].create(
            {
                "endpoint_id": endpoint.id,
                "company_id": self.env.company.id,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "request_body": body.decode(),
                "request_headers_json": "{}",
                "payload_json": "{}",
            }
        )


class TestInboundDispatchOverride(_BackendInboundTestCase):
    """``_invoke_inbound_dispatch`` routes to the linked backend."""

    def test_dispatch_calls_handle_on_linked_backend(self):
        event = self._create_event(self.endpoint)

        result = event._invoke_inbound_dispatch()

        self.assertEqual(result["status"], "done")
        self.assertIn(str(event.id), result["note"])

    def test_dispatch_falls_back_to_super_when_endpoint_has_no_backend(self):
        plain_endpoint = self.env["bwt.webhook.inbound.endpoint"].create(
            {
                "name": "Plain Endpoint",
                "path": f"plain-{self.backend.id}",
                "delivery_identity_policy": "body_sha256",
            }
        )
        event = self._create_event(plain_endpoint)

        result = event._invoke_inbound_dispatch()

        # No backend, no handler_id -> default super returns None
        # ("event was stored only").
        self.assertIsNone(result)


class TestInboundDefaultHandler(_BackendInboundTestCase):
    """The bare backend's default ``_handle_inbound_webhook_event``
    returns ``None``; the dispatcher upgrades that to a dead letter."""

    def test_bare_backend_default_returns_none(self):
        bare = self.env[self.BARE_BACKEND_MODEL].create({"name": "Bare", "code": "bare"})
        event = self._create_event(self.endpoint)

        self.assertIsNone(bare._handle_inbound_webhook_event(event))

    def test_dispatch_upgrades_none_to_dead_letter(self):
        bare = self.env[self.BARE_BACKEND_MODEL].create({"name": "Bare2", "code": "bare2"})
        bare_endpoint = self.env["bwt.webhook.inbound.endpoint"].create(
            {
                "name": "Bare Endpoint",
                "path": f"bare-inbound-{bare.id}",
                "delivery_identity_policy": "body_sha256",
                "connector_backend_ref": f"{bare._name},{bare.id}",
            }
        )
        event = self._create_event(bare_endpoint)

        result = event._invoke_inbound_dispatch()

        self.assertEqual(result["status"], "dead_letter")


class TestInboundComputedField(_BackendInboundTestCase):
    """``webhook_endpoint_id`` resolves to the linked endpoint."""

    def test_compute_returns_linked_endpoint(self):
        self.assertEqual(self.backend.webhook_endpoint_id, self.endpoint)

    def test_compute_returns_empty_when_no_endpoint_linked(self):
        other_backend = self.env[self.BACKEND_MODEL].create({"name": "Other", "code": "other"})

        self.assertFalse(other_backend.webhook_endpoint_id)

    def test_compute_returns_empty_when_reference_is_unset(self):
        from unittest.mock import patch

        with patch.object(type(self.backend), "_get_connector_backend_reference", lambda s: False):
            result = self.backend.webhook_endpoint_id

        self.assertFalse(result)


class TestInboundActionViewEndpoint(_BackendInboundTestCase):
    """``action_view_inbound_endpoint`` opens the linked endpoint form."""

    def test_action_returns_form_view_for_linked_endpoint(self):
        action = self.backend.action_view_inbound_endpoint()

        self.assertEqual(action["res_id"], self.endpoint.id)
        self.assertEqual(action["view_mode"], "form")

    def test_action_raises_when_no_endpoint_linked(self):
        from odoo.exceptions import ValidationError

        backend_no_ep = self.env[self.BACKEND_MODEL].create({"name": "NoEp", "code": "noep"})

        with self.assertRaises(ValidationError):
            backend_no_ep.action_view_inbound_endpoint()
