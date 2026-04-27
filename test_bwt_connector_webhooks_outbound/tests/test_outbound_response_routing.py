"""Tests for outbound response routing to the linked connector backend.

The framework's
``bwt.webhook.outbound.delivery._handle_outbound_response`` hook is
overridden in ``bwt_connector_webhooks_outbound`` to delegate to the
linked backend's ``_handle_outbound_webhook_response`` method,
passing the resolved binding and operation as keyword arguments so
consumers don't re-parse context values.
"""

from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from odoo.addons.bwt_webhooks_core.services.value_objects import (
    HandlerOutcome,
    OutboundRequest,
)


def _outcome(status="send"):
    return HandlerOutcome(
        status=status,
        request=OutboundRequest(
            target_url="https://example.com/x",
            http_method="post",
            request_body_mode="json",
            headers={},
            payload={},
            files={},
        ),
    )


class _BackendOutboundTestCase(TransactionCase):
    BACKEND_MODEL = "bwt.test.connector.webhook.backend.outbound"

    def setUp(self):
        super().setUp()
        self.backend = self.env[self.BACKEND_MODEL].create({"name": "Acme", "code": "acme"})
        self.endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Primary",
                "code": f"primary-{self.backend.id}",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/primary",
                "connector_backend_ref": f"{self.BACKEND_MODEL},{self.backend.id}",
            }
        )
        self.delivery = self.env["bwt.webhook.outbound.delivery"].create(
            {
                "name": "test",
                "endpoint_id": self.endpoint.id,
                "request_headers_json": "{}",
                "payload_json": "{}",
            }
        )


class TestOutboundResponseDispatch(_BackendOutboundTestCase):
    """``_handle_outbound_response`` routes to the linked backend."""

    def test_default_backend_response_handler_is_noop(self):
        # Mixin default returns None and does not raise.
        result = self.backend._handle_outbound_webhook_response(
            self.delivery,
            MagicMock(status_code=200),
            "done",
            _outcome(),
        )
        self.assertIsNone(result)

    def test_response_routes_to_linked_backend_with_binding_and_operation(self):
        binding = self.env["bwt.test.connector.webhook.outbound.binding"].create(
            {
                "name": "ours",
                "backend_id": f"{self.backend._name},{self.backend.id}",
            }
        )
        self.env["bwt.webhook.outbound.delivery.context.line"].create(
            [
                {
                    "delivery_id": self.delivery.id,
                    "key_name": "binding_model",
                    "source_kind": "literal",
                    "literal_value": binding._name,
                },
                {
                    "delivery_id": self.delivery.id,
                    "key_name": "binding_id",
                    "source_kind": "literal",
                    "literal_value": str(binding.id),
                },
                {
                    "delivery_id": self.delivery.id,
                    "key_name": "operation",
                    "source_kind": "literal",
                    "literal_value": "create",
                },
            ]
        )

        captured = []

        def _capture(self, delivery, response, state, outcome, *, binding=False, operation=False):
            captured.append((self.id, delivery.id, response.status_code, state, binding, operation))

        with patch.object(type(self.backend), "_handle_outbound_webhook_response", _capture):
            self.delivery._handle_outbound_response(MagicMock(status_code=200), "done", _outcome())

        self.assertEqual(len(captured), 1)
        backend_id, delivery_id, status_code, state, captured_binding, captured_operation = captured[0]
        self.assertEqual(backend_id, self.backend.id)
        self.assertEqual(delivery_id, self.delivery.id)
        self.assertEqual(status_code, 200)
        self.assertEqual(state, "done")
        self.assertEqual(captured_binding, binding)
        self.assertEqual(captured_operation, "create")

    def test_response_skips_when_no_backend_linked(self):
        orphan_endpoint = self.endpoint.copy(
            {
                "connector_backend_ref": False,
                "code": "orphan-endpoint",
                "name": "Orphan",
            }
        )
        orphan = self.env["bwt.webhook.outbound.delivery"].create(
            {
                "name": "orphan",
                "endpoint_id": orphan_endpoint.id,
                "request_headers_json": "{}",
                "payload_json": "{}",
            }
        )
        # Should not raise.
        orphan._handle_outbound_response(MagicMock(status_code=200), "done", _outcome())


class TestResolveOutboundDeliveryBinding(_BackendOutboundTestCase):
    """Edge cases for ``resolve_outbound_delivery_binding``."""

    BINDING_MODEL = "bwt.test.connector.webhook.outbound.binding"

    def test_returns_empty_when_get_context_values_raises(self):
        with patch.object(type(self.delivery), "_get_context_values", side_effect=Exception("fail")):
            result = self.backend.resolve_outbound_delivery_binding(self.delivery)
        self.assertFalse(result)

    def test_returns_empty_when_no_binding_model_in_context(self):
        # Delivery has no context lines → context_values empty → target_model None
        result = self.backend.resolve_outbound_delivery_binding(self.delivery)
        self.assertFalse(result)

    def test_returns_empty_when_model_name_not_in_env(self):
        result = self.backend.resolve_outbound_delivery_binding(self.delivery, model_name="nonexistent.model")
        self.assertFalse(result)

    def test_returns_empty_when_binding_model_set_but_no_binding_id(self):
        self.env["bwt.webhook.outbound.delivery.context.line"].create(
            {
                "delivery_id": self.delivery.id,
                "key_name": "binding_model",
                "source_kind": "literal",
                "literal_value": self.BINDING_MODEL,
            }
        )
        result = self.backend.resolve_outbound_delivery_binding(self.delivery)
        self.assertFalse(result)

    def test_returns_empty_when_binding_id_does_not_exist(self):
        self.env["bwt.webhook.outbound.delivery.context.line"].create(
            [
                {
                    "delivery_id": self.delivery.id,
                    "key_name": "binding_model",
                    "source_kind": "literal",
                    "literal_value": self.BINDING_MODEL,
                },
                {
                    "delivery_id": self.delivery.id,
                    "key_name": "binding_id",
                    "source_kind": "literal",
                    "literal_value": "999999",
                },
            ]
        )
        result = self.backend.resolve_outbound_delivery_binding(self.delivery)
        self.assertFalse(result)

    def test_returns_empty_when_binding_belongs_to_different_backend(self):
        other_backend = self.env[self.BACKEND_MODEL].create({"name": "Other", "code": "other"})
        binding = self.env[self.BINDING_MODEL].create(
            {
                "name": "theirs",
                "backend_id": f"{other_backend._name},{other_backend.id}",
            }
        )
        self.env["bwt.webhook.outbound.delivery.context.line"].create(
            [
                {
                    "delivery_id": self.delivery.id,
                    "key_name": "binding_model",
                    "source_kind": "literal",
                    "literal_value": binding._name,
                },
                {
                    "delivery_id": self.delivery.id,
                    "key_name": "binding_id",
                    "source_kind": "literal",
                    "literal_value": str(binding.id),
                },
            ]
        )
        result = self.backend.resolve_outbound_delivery_binding(self.delivery)
        self.assertFalse(result)
