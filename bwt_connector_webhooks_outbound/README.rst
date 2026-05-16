==================================
Connector Webhooks - Glue Outbound
==================================

Connector-ready outbound glue for backend-owned delivery flows.

This addon extends Glue Core so teams can keep outbound routing and
delivery ownership attached to the backend records that run the
integration.

**Key Features:**

- Keeps outbound routing tied to the backend that owns the integration.
- Lets delivery decisions stay close to connector-specific logic.
- Supports repeatable outbound operations without rebuilding the same
  glue layer.
- Gives teams a cleaner path from framework setup to live connector
  dispatch.

Who It's For
------------

* Connector teams whose backend records need to own outbound endpoint
  routing.
* Integration teams that want framework-managed recovery while keeping
  connector behavior on the backend.
* Odoo partners packaging outbound delivery behavior as reusable
  connector addons.

Capability Pillars
------------------

* A clear outbound ownership model for backend-led integrations.
* Direct endpoint resolution tied to the connector backend.
* Shared delivery orchestration with room for connector-specific
  decisions.
* Flexible transport support for real-world outbound connector needs.

How It Works
------------

The outbound glue addon keeps routing and delivery ownership on the
backend while the shared framework handles queueing, retries, and
delivery state changes around it.

Technical Validation
--------------------

The technical section below surfaces routing and dispatch flow so
evaluators can inspect how backend ownership, endpoint resolution, and
framework-managed delivery fit together.

.. image:: https://raw.githubusercontent.com/BitwiseHQ/odoo-webhooks/19.0/bwt_connector_webhooks_outbound/static/description/diagrams/webhooks-connector-outbound-routing.svg
   :alt: Outbound endpoint routing by connector backend
   :align: center

Dependencies
------------

* ``bwt_connector_webhooks_core``
* ``bwt_webhooks_outbound``

Implementation Path
-------------------

A typical rollout keeps outbound ownership on the backend while the
framework manages delivery and recovery around it.

1. Prepare the backend so it can own outbound delivery.
2. Seed or install the outbound endpoints that belong to that backend.
3. Let business flows resolve the right endpoint and queue delivery
  work.
4. Let the framework manage dispatch and response handling around the
  connector.
5. Use delivery states to retry, review, or close work cleanly.

Looking for a faster path to live outbound connectors? Pair this glue
layer with premium connector modules such as Stripe when you want a more
turnkey rollout.

Multiple Endpoint Routing
-------------------------

When a backend owns multiple outbound endpoints, use ``code_suffix`` in
``get_outbound_endpoint(code_suffix="...")`` so routing remains stable
across re-sync operations and endpoint refreshes.

Troubleshooting
---------------

* **Wrong endpoint selected:** verify code generation and
  ``code_suffix`` mapping in the concrete addon's XML records.
* **Headers missing at dispatch time:** implement or debug
  ``_get_outbound_extra_headers`` on the backend.
* **Delivery bypasses backend hooks:** confirm endpoint is linked via
  ``connector_backend_ref`` and handler mode routes through connector
  callbacks.

See also `Glue Core README <../bwt_connector_webhooks_core/README.rst>`_
for shared architecture and conventions.

Contributors
------------

* Bitwise Technologies LLC
* Youssef Egla

License
-------

LGPL-3 - `GNU Lesser General Public License v3.0 <http://www.gnu.org/licenses/lgpl-3.0-standalone.html>`_.
