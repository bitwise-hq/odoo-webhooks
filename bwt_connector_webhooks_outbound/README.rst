==================================
Connector Webhooks - Glue Outbound
==================================

Outbound side mixin for connector backends.

Provides ``bwt.connector.webhook.outbound.mixin``, an opt-in abstract
model that extends ``bwt.connector.webhook.backend.base`` with:

* the ``outbound_endpoint_id`` computed Many2one (resolved from the
  endpoint's ``connector_backend_ref``; informational when the
  backend has multiple linked outbound endpoints);
* ``get_outbound_endpoint(endpoint_code, required)`` for
  code-based endpoint resolution;
* the outbound dispatch hook
  (``_handle_outbound_webhook_delivery(delivery, request)``) — the
  framework's
  ``bwt.webhook.outbound.delivery._invoke_handler`` routes deliveries
  whose endpoint carries ``connector_backend_ref`` to this method.
  Backends return ``None`` to send the request unchanged, a gate-style
  result dict (``webhook_done`` / ``webhook_dead_letter`` /
  ``webhook_retry`` / ``webhook_cancel``) to short-circuit the
  request, or ``{"status": "send", "headers": {...}}`` to mutate the
  outgoing request before it is sent;
* the response hook
  (``_handle_outbound_webhook_response(delivery, response, state,
  outcome, *, binding=False, operation=False)``) — invoked from the
  framework's ``_handle_outbound_response`` hook with the resolved
  binding (via ``resolve_outbound_delivery_binding``) and operation
  string parsed from the delivery's context lines;
* ``_get_outbound_api_base_url(delivery)`` and
  ``_get_outbound_extra_headers(delivery)`` per-backend hooks consumed
  by the framework when rendering the absolute URL and merging
  request headers (so concrete backends never re-implement OutboundRequest);
* ``queue_outbound_delivery`` (delivery factory) and the
  ``action_view_outbound_endpoint`` form/list action.

Also extends ``bwt.webhook.outbound.endpoint`` with a
``connector_backend_ref`` reference field.

Concrete handler/endpoint records are shipped by downstream addons as
Odoo XML data and linked to a backend by an administrator (no
auto-provisioning).

Contributors
------------

* Bitwise Technologies LLC
* Youssef Egla

License
-------

Proprietary - `Odoo Proprietary License v1.0 (OPL-1) <https://www.odoo.com/documentation/user/legal/licenses.html>`_.
