Connector Webhooks Core — Operator Guide
=========================================

This guide explains the connector layer of the webhook framework and how an
operator links connector backends to their webhook endpoints through the UI.

What is the Connector Layer?
-----------------------------

The connector layer bridges the webhook framework with OCA connector backends
(e.g. a Stripe or payment gateway backend). Each connector backend record in
Odoo can own one or more webhook endpoints. The connector layer provides:

- A computed **Inbound Endpoint** smart button on backend forms (when
  ``bwt_connector_webhooks_inbound`` is installed).
- A computed **Outbound Endpoint** smart button on backend forms (when
  ``bwt_connector_webhooks_outbound`` is installed).
- Scoped technical naming so endpoint codes are unique per backend instance and
  company.

Endpoints are seeded as Odoo XML data records by the concrete connector addon
(e.g. ``bwt_stripe_core``). They are **not** auto-created when a backend record
is first created.

Linking an Endpoint to a Backend
----------------------------------

If an endpoint has not been automatically linked by the installer, link it
manually:

1. Go to **Webhooks → Inbound → Endpoints** (or Outbound → Endpoints) and
   open the endpoint record you want to link.
2. In the **Connector Backend** field, select the backend model and the specific
   backend record.
3. Save the endpoint.

The smart button on the backend form will now resolve to this endpoint.

Multiple Backends and Endpoint Scoping
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each connector backend instance gets its own endpoint records scoped by a
technical prefix derived from the backend model name and record ID (e.g.
``stripe-1-inbound``). This ensures codes are unique across companies and
backend instances.

Do not manually change the **Code** field on an endpoint that is linked to a
backend; the scoping convention is enforced by the provisioning hooks in the
concrete connector addon and resync operations depend on it.

Verifying the Link
~~~~~~~~~~~~~~~~~~~

Open the backend form. The **Inbound Endpoint** and/or **Outbound Endpoint**
smart buttons should show the linked endpoint name and navigate directly to the
endpoint configuration on click.

If a smart button shows 0 or is absent, the corresponding side addon
(``bwt_connector_webhooks_inbound`` or ``bwt_connector_webhooks_outbound``) may
not be installed, or no endpoint with a matching ``connector_backend_ref`` value
exists yet.

Troubleshooting Checklist
--------------------------

- **Smart button shows 0 or is absent**: install the side addon or ask the
  concrete connector addon to seed its endpoint XML data and run the installer.
- **Multiple endpoints linked to the same backend**: for inbound, only one
  endpoint should be linked per backend instance. For outbound, multiple
  endpoints are valid (one per endpoint spec). Check the addon's ``data/``
  folder for duplicate ``connector_backend_ref`` values.
- **Endpoint code conflicts on install**: the concrete connector addon's XML
  data may have a conflicting code; inspect the ``data/`` folder for the
  endpoint record and ensure the code follows the ``<prefix>-<suffix>``
  convention and is unique.
- **Backend not appearing in Connector Backend selection**: ensure the concrete
  connector addon inherits both ``connector.backend`` and the appropriate
  webhook mixin, and that the addon is installed.
