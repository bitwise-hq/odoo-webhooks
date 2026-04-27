"""Tests for the connector-aware outbound dispatch override.

The connector outbound overlay overrides
``bwt.webhook.outbound.delivery._invoke_handler`` to dispatch
directly to the linked backend's
``_handle_outbound_webhook_delivery`` when no ``handler_id`` is
configured on the endpoint, removing the historical
``bwt.webhook.handler`` proxy step.
"""

from odoo.tests.common import TransactionCase

from odoo.addons.bwt_webhooks_core.services.value_objects import OutboundRequest


def _request():
    return OutboundRequest(
        target_url="https://example.com/v1/x",
        http_method="post",
        request_body_mode="json",
        headers={"X-Base": "1"},
        payload={},
        files={},
    )


class _BackendOutboundTestCase(TransactionCase):
    BACKEND_MODEL = "bwt.test.connector.webhook.backend.outbound.hooked"

    def setUp(self):
        super().setUp()
        self.backend = self.env[self.BACKEND_MODEL].create({"name": "Hook", "code": "hook"})
        self.endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Hooked Endpoint",
                "code": f"hooked-{self.backend.id}",
                "http_method": "post",
                "target_path": "/v1/x",
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


class TestExtraHeadersMerge(_BackendOutboundTestCase):
    """The default ``_handle_outbound_webhook_delivery`` merges
    :meth:`_get_outbound_extra_headers` into the request headers."""

    def test_default_orchestration_merges_extra_headers(self):
        self.env["bwt.webhook.outbound.delivery.context.line"].create(
            {
                "delivery_id": self.delivery.id,
                "key_name": "idempotency_key",
                "source_kind": "literal",
                "literal_value": "k-123",
            }
        )

        result = self.backend._handle_outbound_webhook_delivery(self.delivery, _request())

        self.assertEqual(result["status"], "send")
        merged = result["headers"]
        self.assertEqual(merged["X-Base"], "1")
        self.assertEqual(merged["Authorization"], "Bearer test-token")
        self.assertEqual(merged["Idempotency-Key"], "k-123")

    def test_dispatch_gate_short_circuits(self):
        self.backend.dispatch_blocked = True

        result = self.backend._handle_outbound_webhook_delivery(self.delivery, _request())

        self.assertEqual(result["status"], "dead_letter")


class TestInvokeHandlerOverride(_BackendOutboundTestCase):
    """``_invoke_handler`` routes to the backend when no handler_id."""

    def test_dispatch_goes_to_backend_when_no_handler(self):
        # ``_invoke_handler`` returns a HandlerOutcome carrying the
        # mutated request when the backend hook returns
        # ``{"status": "send", "headers": ...}``.
        outcome = self.delivery._invoke_handler(_request())
        self.assertEqual(outcome.status, "send")
        self.assertEqual(outcome.request.headers["Authorization"], "Bearer test-token")

    def test_default_passthrough_when_backend_returns_none(self):
        # Bare backend has no ``_get_outbound_extra_headers`` overrides
        # and no dispatch gate, so its dispatch hook returns ``None``;
        # ``_invoke_handler`` collapses that to a plain ``send``.
        bare = self.env["bwt.test.connector.webhook.backend.outbound.bare"].create({"name": "b", "code": "b"})
        bare_endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Bare",
                "code": f"bare-{bare.id}",
                "http_method": "post",
                "target_path": "/x",
                "connector_backend_ref": f"{bare._name},{bare.id}",
            }
        )
        bare_delivery = self.env["bwt.webhook.outbound.delivery"].create(
            {
                "name": "bare",
                "endpoint_id": bare_endpoint.id,
                "request_headers_json": "{}",
                "payload_json": "{}",
            }
        )
        outcome = bare_delivery._invoke_handler(_request())
        self.assertEqual(outcome.status, "send")
        self.assertEqual(outcome.request.headers, {"X-Base": "1"})

    def test_invoke_handler_falls_through_to_super_when_no_backend(self):
        """False branch of ``if backend and not self.handler_id`` when no backend."""
        endpoint_no_backend = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "No Backend Dispatch",
                "code": "no-backend-dispatch",
                "http_method": "post",
                "target_path": "/x",
                "target_hostname": "https://example.com",
            }
        )
        delivery = self.env["bwt.webhook.outbound.delivery"].create(
            {
                "name": "test-no-backend",
                "endpoint_id": endpoint_no_backend.id,
                "request_headers_json": "{}",
                "payload_json": "{}",
            }
        )
        # No backend → falls through to super()._invoke_handler which returns SEND
        outcome = delivery._invoke_handler(_request())
        self.assertEqual(outcome.status, "send")

    def test_resolve_outbound_response_context_exception_returns_false(self):
        """``except Exception`` in ``_resolve_outbound_response_context`` returns False, False."""
        from unittest.mock import patch

        with patch.object(
            type(self.delivery),
            "_get_context_values",
            side_effect=Exception("fail"),
        ):
            binding, operation = self.delivery._resolve_outbound_response_context(self.backend)

        self.assertFalse(binding)
        self.assertFalse(operation)
