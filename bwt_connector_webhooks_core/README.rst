==============================
Connector Webhooks - Glue Core
==============================

Shared glue infrastructure for connector backends that need webhook
ownership, cleaner rollout patterns, and a stronger operational base.

Glue Core gives connector teams one shared foundation for backend-owned
webhook flows so inbound and outbound rollout can stay consistent as
the connector line grows.

**Highlights:**

- Gives connector teams one shared ownership model across webhook
  flows.
- Keeps rollout and refresh work more predictable over time.
- Helps endpoint naming and routing stay consistent as connector scope
  grows.
- Supports inbound-only, outbound-only, or combined connector rollouts.

Who It's For
------------

* Teams productising connector backends that need webhook ownership to
  live on backend records.
* Integration teams that want one shared glue layer before expanding
  into inbound and outbound behavior.
* Odoo partners standardising connector-backed rollout patterns across
  multiple addons.

Capability Pillars
------------------

* One shared foundation for backend-owned webhook rollout.
* Clear backend linkage that keeps ownership and routing aligned.
* Stable naming and provisioning patterns that reduce drift over time.
* Directional expansion paths so teams only add the behavior they need.

How It Works
------------

Glue Core establishes the shared ownership model first, then the
directional glue addons layer inbound and outbound behavior on top so
connector teams can grow without rebuilding the same foundation for each
flow.

Technical Validation
--------------------

The technical section below surfaces backend linking flow and
orchestration details so evaluators can inspect how backend records,
endpoint references, and directional glue pieces fit together.

.. image:: https://raw.githubusercontent.com/BitwiseHQ/odoo-webhooks/19.0/bwt_connector_webhooks_core/static/description/diagrams/webhooks-connector-backend-linking.svg
   :alt: Connector backend linking flow
   :align: center

Implementation Path
-------------------

Start with Glue Core when the backend record should be the place where
webhook ownership and rollout decisions live.

1. Install ``bwt_connector_webhooks_core`` to give backend records a
  shared ownership layer.
2. Add inbound glue where the backend needs to receive provider
  traffic.
3. Add outbound glue where the backend needs to send deliveries.
4. Link each endpoint to the backend record it belongs to.

Looking for a faster path from glue layer to live integration? Pair
this foundation with premium connector modules such as Stripe when you
want a more turnkey rollout.

Further Reading
---------------

* `Operator Guide <readme/OPERATOR_GUIDE.rst>`_
* `Developer Guide <readme/DEVELOPER_GUIDE.rst>`_
* `Glue Inbound README <../bwt_connector_webhooks_inbound/README.rst>`_
* `Glue Outbound README <../bwt_connector_webhooks_outbound/README.rst>`_

Contributors
------------

* Bitwise Technologies LLC
* Youssef Egla

License
-------

LGPL-3 - `GNU Lesser General Public License v3.0 <http://www.gnu.org/licenses/lgpl-3.0-standalone.html>`_.
