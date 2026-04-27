Reliable outbound webhook delivery for Odoo with templated requests,
retries, and detailed diagnostics.

**Highlights:**

- Endpoint registry with method, body mode, and timeout controls.
- Tokenized paths plus header and payload rules for dynamic requests.
- Queue-backed delivery with retry and dead-letter handling.
- Per-attempt response logging for diagnostics and SLAs.
- Delivery context lines to map Odoo data into requests.
- Designed to plug into connector-backed integrations.

.. image:: static/description/diagrams/webhooks-outbound-flow.svg
   :alt: Outbound delivery flow
   :align: center

.. image:: static/description/diagrams/webhooks-outbound-sequence.svg
   :alt: Outbound delivery sequence
   :align: center

Looking for turnkey integrations? Pair this framework with premium
connector addons (e.g., Stripe) to launch faster.
