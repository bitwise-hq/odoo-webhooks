Secure inbound webhook endpoints for Odoo with signatures, replay
protection, and rule-based processing.

**Highlights:**

- Public endpoints with HMAC signature verification (SHA1/256/512, hex/base64).
- Timestamp and idempotency controls to block replayed events.
- Declarative rules to create, update, or upsert Odoo records.
- Semantic bindings to normalize payload fields for consistent rules.
- Full event audit trail with state, retries, and dead-letter flows.
- Operator-friendly views for endpoints, rules, and events.

.. image:: static/description/diagrams/webhooks-inbound-flow.svg
   :alt: Inbound request flow
   :align: center

.. image:: static/description/diagrams/webhooks-inbound-sequence.svg
   :alt: Inbound processing sequence
   :align: center

Looking for turnkey integrations? Pair this framework with premium
connector addons (e.g., Stripe) to launch faster.
