Webhooks
========

This addon provides the first implementation slice for a generic webhook
framework in Odoo.

Current scope
-------------

* inbound webhook endpoints with public HTTP intake
* model-driven source configuration for canonical webhook fields
* HMAC signature verification with multipart message assembly
* durable inbound event storage with idempotency protection
* queue-backed Python handler execution

Follow-up slices will extend the low-code action layer, outbound delivery, and
provider presets.