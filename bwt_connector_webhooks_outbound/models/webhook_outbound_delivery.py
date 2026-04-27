"""Connector-aware override for ``bwt.webhook.outbound.delivery``.

Two responsibilities:

1. Dispatch the framework's ``_invoke_handler`` directly to the
   linked connector backend's ``_handle_outbound_webhook_delivery``
   when no ``handler_id`` is configured on the endpoint, removing
   the need for a ``bwt.webhook.handler`` proxy row per connector
   operation.

2. Resolve the ``(binding, operation)`` pair from the delivery's
   context lines once and pass them to the backend's
   ``_handle_outbound_webhook_response`` override so consumers do
   not need to re-parse context values.
"""

from odoo import models

from odoo.addons.bwt_webhooks_core.services.value_objects import (
    OUTCOME_SEND,
    HandlerOutcome,
    OutboundRequest,
)


class WebhookOutboundDelivery(models.Model):
    _inherit = "bwt.webhook.outbound.delivery"

    # ------------------------------------------------------------------
    # Dispatch: backend hook replaces the handler proxy when present
    # ------------------------------------------------------------------
    def _invoke_handler(self, request: OutboundRequest) -> HandlerOutcome:
        self.ensure_one()
        backend = self.endpoint_id.connector_backend_ref
        if backend and not self.handler_id:
            raw = backend._handle_outbound_webhook_delivery(self, request)
            if raw is None:
                return HandlerOutcome(status=OUTCOME_SEND, request=request)
            return self._resolve_handler_outcome(raw, request)
        return super()._invoke_handler(request)

    # ------------------------------------------------------------------
    # Response: pass resolved binding + operation to the backend hook
    # ------------------------------------------------------------------
    def _handle_outbound_response(self, response, state, outcome):
        res = super()._handle_outbound_response(response, state, outcome)
        for delivery in self:
            backend = delivery.endpoint_id.connector_backend_ref
            if not backend:
                continue
            binding, operation = delivery._resolve_outbound_response_context(backend)
            backend._handle_outbound_webhook_response(
                delivery,
                response,
                state,
                outcome,
                binding=binding,
                operation=operation,
            )
        return res

    def _resolve_outbound_response_context(self, backend):
        """Return ``(binding, operation)`` resolved from context lines.

        Only used internally to feed the backend hook. Failures
        (missing model, deleted row, cross-backend reference) collapse
        to ``False`` so the response hook still runs.
        """
        self.ensure_one()
        try:
            context_values = self._get_context_values()
        except Exception:  # pylint: disable=broad-except
            return False, False
        operation = context_values.get("operation") or False
        binding = backend.resolve_outbound_delivery_binding(self) if backend else False
        return binding or False, operation
