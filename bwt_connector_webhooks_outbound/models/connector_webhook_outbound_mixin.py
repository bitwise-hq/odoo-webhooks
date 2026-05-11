"""Outbound side mixin for connector backends.

Extends :class:`bwt.connector.webhook.backend.base` with outbound
delivery queueing, the per-backend dispatch hook called by the
connector-aware delivery override, and a couple of convenience
helpers.

A concrete connector backend opts in by listing both
``connector.backend`` and ``bwt.connector.webhook.outbound.mixin`` in
its ``_inherit`` (and additionally
``bwt.connector.webhook.inbound.mixin`` when it also receives inbound
webhooks).

Endpoint records are seeded as XML data by the concrete connector
addon; this mixin does not create or update
``bwt.webhook.outbound.endpoint`` rows.
"""

import json

from odoo import fields, models, _
from odoo.exceptions import ValidationError

from odoo.addons.bwt_connector_webhooks_core.services.values import (
    json_serialize_value,
)


class ConnectorWebhookOutboundMixin(models.AbstractModel):
    _name = "bwt.connector.webhook.outbound.mixin"
    _inherit = "bwt.connector.webhook.backend.base"
    _description = "Connector Webhook Outbound Mixin"

    api_base_url = fields.Char(
        string="API Base URL",
        help=("Default base URL applied to outbound endpoints linked to this backend. Concrete backends with mode-aware hostnames (e.g. ``test``/``live``) override ``_get_outbound_api_base_url`` to ignore this default."),
    )
    outbound_endpoint_id = fields.Many2one(
        "bwt.webhook.outbound.endpoint",
        string="Outbound Endpoint",
        compute="_compute_outbound_endpoint_id",
        readonly=True,
    )

    def _compute_outbound_endpoint_id(self):
        endpoint_model = self.env["bwt.webhook.outbound.endpoint"]
        for backend in self:
            ref = backend._get_connector_backend_reference()
            if not ref:
                backend.outbound_endpoint_id = endpoint_model
                continue
            backend.outbound_endpoint_id = endpoint_model.search(
                [("connector_backend_ref", "=", ref)],
                limit=1,
            )

    # ==================================================================
    # Endpoint resolution
    # ==================================================================
    def _get_linked_outbound_endpoints(self):
        self.ensure_one()
        return self.env["bwt.webhook.outbound.endpoint"].search([("connector_backend_ref", "=", self._get_connector_backend_reference())])

    def get_outbound_endpoint(self, endpoint_code=False, code_suffix=False, required=True):
        """Return one outbound endpoint linked to this backend.

        Filters (in order of precedence):

        * ``code_suffix`` -- match the per-spec stable identifier
          shipped by connector addon XML data. Preferred for
          multi-backend installs.
        * ``endpoint_code`` -- match the materialized ``code``
          column. Use when the caller has the full backend-scoped code.
        """
        self.ensure_one()
        linked = self._get_linked_outbound_endpoints()
        if code_suffix:
            linked = linked.filtered(lambda r: r.code_suffix == code_suffix)
            selector = _("code suffix '%(value)s'", value=code_suffix)
        elif endpoint_code:
            linked = linked.filtered(lambda r: r.code == endpoint_code)
            selector = _("code '%(value)s'", value=endpoint_code)
        else:
            selector = None
        if selector and not linked:
            if required:
                raise ValidationError(
                    _(
                        "No outbound webhook endpoint with %(selector)s is linked to connector backend %(name)s.",
                        selector=selector,
                        name=self.display_name,
                    )
                )
            return self.env["bwt.webhook.outbound.endpoint"]
        if selector:
            return linked[:1]
        if not linked:
            if required:
                raise ValidationError(
                    _(
                        "No outbound webhook endpoint is linked to connector backend %(name)s.",
                        name=self.display_name,
                    )
                )
            return self.env["bwt.webhook.outbound.endpoint"]
        if len(linked) > 1:
            raise ValidationError(
                _(
                    "Multiple outbound webhook endpoints are linked to connector backend %(name)s; specify ``code_suffix`` or ``endpoint_code``.",
                    name=self.display_name,
                )
            )
        return linked

    # ==================================================================
    # Hostname / header hooks
    # ==================================================================
    def _get_outbound_api_base_url(self, delivery=None):  # noqa: ARG002
        """Return the API base URL for an outbound delivery.

        Default returns the generic :attr:`api_base_url`. Concrete
        backends with mode-aware hostnames (test vs live, regional
        endpoints, ...) override this hook.
        """
        self.ensure_one()
        return self.api_base_url or False

    def _get_outbound_extra_headers(self, delivery):  # noqa: ARG002
        """Return headers merged into every outbound delivery request.

        Default empty. Concrete backends contribute authentication
        (``Authorization``, API-version headers) and per-delivery
        values (``Idempotency-Key`` from the delivery's context lines)
        here. Returned headers are merged on top of the configured
        endpoint header rules.
        """
        self.ensure_one()
        return {}

    # ==================================================================
    # Dispatch hook (called by the connector-aware delivery override)
    # ==================================================================
    def _check_outbound_dispatch_allowed(self, delivery):  # noqa: ARG002
        """Pre-send gate.

        Return ``None`` to allow the delivery, or a result dict from
        :mod:`bwt_connector_webhooks_core.services.result_types`
        (``webhook_dead_letter`` / ``webhook_cancel`` / ``webhook_retry``)
        to short-circuit.
        """
        self.ensure_one()
        return None

    def _handle_outbound_webhook_delivery(self, delivery, request):
        """Backend dispatch hook called by the delivery override.

        ``request`` is the framework's
        :class:`~odoo.addons.bwt_webhooks_core.services.value_objects.OutboundRequest`
        for the delivery. The hook returns one of:

        * ``None`` -- proceed; merge :meth:`_get_outbound_extra_headers`
          onto the request headers and send.
        * a result dict from
          :mod:`bwt_connector_webhooks_core.services.result_types`
          (``webhook_dead_letter`` / ``webhook_cancel`` / ``webhook_retry``)
          -- short-circuits the dispatch with the matching outcome.
        * a raw handler-style dict ``{"status": "send", ...}`` --
          forwarded unchanged to ``HandlerOutcome.from_raw`` for full
          control over the request mutation. Use sparingly.
        """
        self.ensure_one()
        gate = self._check_outbound_dispatch_allowed(delivery)  # pylint: disable=assignment-from-none
        if gate is not None:
            return gate
        extra_headers = self._get_outbound_extra_headers(delivery) or {}
        if not extra_headers:
            return None
        merged_headers = {**request.headers, **extra_headers}
        return {"status": "send", "headers": merged_headers}

    def _handle_outbound_webhook_response(self, delivery, response, state, outcome, *, binding=False, operation=False):  # noqa: ARG002
        """Per-backend post-response hook (override in consuming addons).

        Called from ``bwt.webhook.outbound.delivery._handle_outbound_response``
        after the framework has recorded the HTTP outcome. The
        connector overlay resolves the binding and operation from the
        delivery's context lines once and passes them in so concrete
        backends do not have to re-parse context values.

        :param delivery: the :class:`bwt.webhook.outbound.delivery`.
        :param response: the :class:`requests.Response` returned by the
            transport layer.
        :param state: ``'done'``, ``'dead_letter'`` or ``'error'``.
        :param outcome: the :class:`HandlerOutcome` from the prepare
            phase.
        :param binding: the connector binding referenced by the
            delivery's ``binding_model`` / ``binding_id`` context, or
            ``False`` if the delivery does not carry a binding ref or
            the referenced binding no longer exists.
        :param operation: the operation name from the delivery's
            ``operation`` context line, or ``False``.
        """
        self.ensure_one()
        return

    # ==================================================================
    # Outbound delivery queueing
    # ==================================================================
    def queue_outbound_delivery(
        self,
        endpoint,
        name,
        payload=None,
        headers=None,
        context_values=None,
        auto_queue=True,
    ):
        """Create a ``bwt.webhook.outbound.delivery`` and (optionally) queue it.

        ``endpoint`` must be linked to ``self``. ``context_values`` are
        materialized as ``bwt.webhook.outbound.delivery.context.line``
        rows used by :meth:`_handle_outbound_webhook_delivery` and
        :meth:`_handle_outbound_webhook_response` to look up records
        during request preparation and response handling, and by the
        framework to interpolate ``{token}`` placeholders in the
        endpoint's ``target_path``.
        """
        self.ensure_one()
        self._validate_outbound_endpoint_for_queue(endpoint)
        delivery = self.env["bwt.webhook.outbound.delivery"].create(
            {
                "name": name,
                "endpoint_id": endpoint.id,
                "request_headers_json": json.dumps(headers or {}, sort_keys=True),
                "payload_json": json.dumps({} if payload is None else payload, sort_keys=True),
            }
        )
        if context_values:
            self.env["bwt.webhook.outbound.delivery.context.line"].create(
                [
                    {
                        "delivery_id": delivery.id,
                        "key_name": key,
                        "source_kind": "literal",
                        "literal_value": json_serialize_value(value),
                    }
                    for key, value in context_values.items()
                ]
            )
        if auto_queue:
            delivery.action_queue_delivery()
        return delivery

    def _validate_outbound_endpoint_for_queue(self, endpoint):
        if not endpoint or endpoint._name != "bwt.webhook.outbound.endpoint":
            raise ValidationError(_("An outbound webhook endpoint record must be provided when queueing a delivery."))
        linked_backend = endpoint.connector_backend_ref
        if not linked_backend or linked_backend._name != self._name or linked_backend.id != self.id:
            raise ValidationError(_("The selected outbound webhook endpoint is not linked to this connector backend."))

    # ==================================================================
    # Helpers
    # ==================================================================
    def resolve_outbound_delivery_binding(self, delivery, model_name=None):
        """Resolve the binding referenced by an outbound delivery's context.

        Returns the binding recordset (empty if the delivery does not
        carry a binding ref, the model is not installed, the row was
        deleted, or the row belongs to a different backend).

        ``model_name`` is optional and defaults to the value of the
        ``binding_model`` context line.
        """
        self.ensure_one()
        try:
            context_values = delivery._get_context_values()
        except Exception:  # pylint: disable=broad-except
            return self.env["bwt.connector.webhook.outbound.mixin"].browse()
        target_model = model_name or context_values.get("binding_model")
        if not target_model or target_model not in self.env:
            return self.env["bwt.connector.webhook.outbound.mixin"].browse()
        binding_id = context_values.get("binding_id")
        if not binding_id:
            return self.env[target_model].browse()
        record = self.env[target_model].browse(int(binding_id)).exists()
        if not record:
            return self.env[target_model]
        backend = getattr(record, "backend_id", False)
        if backend and backend != self:
            return self.env[target_model]
        return record

    # ==================================================================
    # Action
    # ==================================================================
    def action_view_outbound_endpoint(self):
        self.ensure_one()
        endpoints = self._get_linked_outbound_endpoints()
        if not endpoints:
            raise ValidationError(_("No outbound webhook endpoint is linked to this backend."))
        if len(endpoints) == 1:
            return self._action_view_single_outbound_endpoint(endpoints)
        return self._action_view_outbound_endpoint_list()

    def _action_view_single_outbound_endpoint(self, endpoint):
        action = self.env.ref("bwt_webhooks_outbound.action_webhook_outbound_endpoint").read()[0]
        action.update(
            {
                "res_id": endpoint.id,
                "view_mode": "form",
                "views": [
                    (
                        self.env.ref("bwt_webhooks_outbound.view_webhook_outbound_endpoint_form").id,
                        "form",
                    ),
                ],
            }
        )
        return action

    def _action_view_outbound_endpoint_list(self):
        action = self.env.ref("bwt_webhooks_outbound.action_webhook_outbound_endpoint").read()[0]
        backend_ref = self._get_connector_backend_reference()
        action.update(
            {
                "domain": [("connector_backend_ref", "=", backend_ref)],
                "view_mode": "list,form",
                "views": [
                    (
                        self.env.ref("bwt_webhooks_outbound.view_webhook_outbound_endpoint_list").id,
                        "list",
                    ),
                    (
                        self.env.ref("bwt_webhooks_outbound.view_webhook_outbound_endpoint_form").id,
                        "form",
                    ),
                ],
                "context": {"default_connector_backend_ref": backend_ref},
            }
        )
        return action
