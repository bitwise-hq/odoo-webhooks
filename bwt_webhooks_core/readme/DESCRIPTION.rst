Production-grade webhook orchestration for Odoo, providing the shared
engine used by inbound and outbound addons.

**Highlights:**

- Unified handler model with clear inbound/outbound separation.
- Rule-driven execution or Python callbacks for advanced logic.
- Queue-backed job definitions and async execution primitives.
- Security groups and access rules for webhook administration.
- Stable primitives for connector-backed integrations.

.. image:: static/description/diagrams/webhooks-core-entities.svg
   :alt: Core data model
   :align: center

Looking for turnkey integrations? Pair this framework with premium
connector addons (e.g., Stripe) to launch faster.
