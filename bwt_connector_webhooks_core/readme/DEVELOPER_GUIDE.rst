Connector Webhooks - Glue Core - Developer Guide
================================================

This guide covers building a new connector backend addon that integrates with
the webhook framework via the connector layer mixins.

Architecture Overview
----------------------

The connector layer consists of three abstract models:

- ``bwt.connector.webhook.backend.base`` — private shared base; not inherited
  directly. Provides code normalization, scoping primitives, and the integration
  contract marker.
- ``bwt.connector.webhook.inbound.mixin`` — opt-in mixin for backends that
  receive inbound webhooks.
- ``bwt.connector.webhook.outbound.mixin`` — opt-in mixin for backends that
  send outbound webhooks.

Concrete backends combine these with the OCA ``connector.backend`` model.

Registering a Backend
----------------------

Declare the backend model in your concrete connector addon::

    class MyServiceBackend(models.Model):
        _name = "my_service.backend"
        _inherit = [
            "connector.backend",
            "bwt.connector.webhook.inbound.mixin",
            "bwt.connector.webhook.outbound.mixin",
        ]
        _description = "My Service Backend"

        name = fields.Char(required=True)
        code = fields.Char(required=True)
        company_id = fields.Many2one("res.company", required=True)
        active = fields.Boolean(default=True)
        api_key = fields.Char(string="API Key")

The ``_is_connector_webhook_backend = True`` marker is set automatically by the
base; your model is enrolled in the backend reference selection without further
configuration.

Technical Prefix
~~~~~~~~~~~~~~~~~

Override ``_get_technical_prefix()`` to return a stable, human-readable prefix::

    def _get_technical_prefix(self):
        self.ensure_one()
        return f"my-service-{self.id}"

The default prefix is ``<model-token>-<id>``. A custom prefix keeps codes
stable across model renames and readable in the admin UI.

Inbound Integration
--------------------

Override ``_handle_inbound_webhook_event`` to process events routed to this
backend::

    def _handle_inbound_webhook_event(self, event):
        self.ensure_one()
        payload = event.get_payload()
        event_type = payload.get("type", "")
        if event_type == "payment.completed":
            self._handle_payment(payload)
            return event.webhook_done()
        return event.webhook_dead_letter()

Valid return values from ``bwt_connector_webhooks_core.services.result_types``:

- ``event.webhook_done()`` — processing complete.
- ``event.webhook_dead_letter()`` — permanent failure; requires manual review.
- ``event.webhook_retry(seconds=60)`` — re-enqueue after a delay.
- ``event.webhook_cancel()`` — silently cancel without marking as error.

Returning ``None`` produces a framework-level dead-letter.

The handler record for this backend's inbound endpoint must use **Python
Callback** mode pointing to ``my_service.backend`` and
``_handle_inbound_webhook_event``. Seed it as an XML data record in your addon.

Outbound Integration
---------------------

Override the following hooks on your backend model.

Dynamic hostname (required when the URL changes between modes)::

    def _get_outbound_api_base_url(self, delivery=None):
        self.ensure_one()
        return "https://api.my-service.com"

Authentication headers (required for most APIs)::

    def _get_outbound_extra_headers(self, delivery):
        self.ensure_one()
        return {"Authorization": f"Bearer {self.api_key}"}

Pre-send gate (optional — short-circuit before dispatch)::

    def _check_outbound_dispatch_allowed(self, delivery):
        self.ensure_one()
        if not self.active:
            return delivery.webhook_cancel()
        return None

Main dispatch handler (required when using Python Callback mode)::

    def _handle_outbound_webhook_delivery(self, delivery):
        self.ensure_one()
        return delivery._build_outbound_delivery_result(outcome="send")

Endpoint Seeding
-----------------

Endpoint records are seeded as XML data in your concrete connector addon's
``data/`` folder. They are linked to backends via the ``connector_backend_ref``
field. Do not auto-provision endpoints from Python code; keep them as
declarative XML records to stay upgrade-safe.

Example inbound endpoint record::

    <record id="my_service_inbound_endpoint" model="bwt.webhook.inbound.endpoint">
        <field name="name">My Service Inbound</field>
        <field name="path">/webhooks/my-service</field>
        <field name="handler_id" ref="my_service_inbound_handler"/>
        <field name="signature_mode">hmac</field>
        <field name="signature_digest">sha256</field>
        <field name="signature_encoding">hex</field>
    </record>

After install, link the endpoint to the backend by setting
``connector_backend_ref`` or by following the UI steps in the Operator Guide.

Resolving the Linked Outbound Endpoint
----------------------------------------

When queueing an outbound delivery from your business logic::

    backend = self.env["my_service.backend"].browse(backend_id)
    endpoint = backend.get_outbound_endpoint()
    delivery = endpoint.queue_delivery(
        payload={"event": "order.paid", "order_id": order.id},
        context_lines={"idempotency_key": str(uuid.uuid4())},
    )

Use ``code_suffix`` when a backend has multiple outbound endpoints::

    endpoint = backend.get_outbound_endpoint(code_suffix="orders")

The ``code_suffix`` value must match the ``code_suffix`` column on the endpoint
record, which is set by the concrete addon's XML data.
