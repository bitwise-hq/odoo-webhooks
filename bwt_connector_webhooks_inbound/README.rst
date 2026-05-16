=================================
Connector Webhooks - Glue Inbound
=================================

Connector-ready inbound glue for backend-owned webhook entry points.

This addon adds inbound connector behavior on top of Glue Core so teams
can keep provider-facing intake attached to the backend records that own
the integration.

**Key Features:**

- Keeps inbound webhook ownership tied to the backend that runs the
  integration.
- Lets provider-specific handling stay close to the connector logic.
- Makes endpoint access and operations easier for day-to-day teams.
- Supports a cleaner path from framework setup to provider rollout.

Who It's For
------------

* Connector teams whose backend records need to own inbound webhook
  entry points.
* Integration teams that want secure intake while keeping connector
  behavior anchored to the backend.
* Odoo partners packaging inbound connector behavior as a reusable
  backend addon.

Capability Pillars
------------------

* A clear inbound ownership model for backend-led integrations.
* Direct linkage between the backend record and the receiving endpoint.
* Framework-backed validation with backend-level handling where it
  matters.
* Faster navigation for teams managing inbound connector operations.

How It Works
------------

The inbound glue addon connects the backend record to the right entry
point, lets the framework handle intake and validation, then hands the
event to the connector so provider-specific behavior stays where the
integration team expects it.

Technical Validation
--------------------

The technical section below surfaces backend-to-endpoint linkage and
dispatch flow so evaluators can inspect where validation ends and
backend-specific processing begins.

.. image:: https://raw.githubusercontent.com/BitwiseHQ/odoo-webhooks/19.0/bwt_connector_webhooks_inbound/static/description/diagrams/webhooks-connector-backend-linking.svg
   :alt: Inbound backend-to-endpoint linking
   :align: center

Dependencies
------------

* ``bwt_connector_webhooks_core``
* ``bwt_webhooks_inbound``

Implementation Path
-------------------

A typical rollout keeps endpoint ownership on the backend while the
framework handles intake and validation around it.

1. Prepare the backend so it can own inbound webhook traffic.
2. Seed or install the inbound endpoints that belong to that backend.
3. Link each endpoint to the backend record it serves.
4. Let the framework receive and validate incoming requests before the
  connector handles them.
5. Use backend logic to complete the event, retry it, or route it for
  follow-up.

Looking for a faster path to live inbound connectors? Pair this glue
layer with premium connector modules such as Stripe when you want a more
turnkey rollout.

Troubleshooting
---------------

* **Inbound smart button is missing:** ensure
  ``bwt_connector_webhooks_inbound`` is installed and the backend model
  inherits the inbound mixin.
* **Endpoint not resolved:** verify ``connector_backend_ref`` points to
  the correct backend model and record.
* **Events not routed to backend callback:** confirm the endpoint's
  handler uses Python Callback mode and points to
  ``_handle_inbound_webhook_event``.

See also `Glue Core README <../bwt_connector_webhooks_core/README.rst>`_
for architecture and shared conventions.

Contributors
------------

* Bitwise Technologies LLC
* Youssef Egla

License
-------

LGPL-3 - `GNU Lesser General Public License v3.0 <http://www.gnu.org/licenses/lgpl-3.0-standalone.html>`_.
