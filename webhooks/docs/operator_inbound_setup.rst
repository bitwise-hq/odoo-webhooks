Operator Guide: Inbound Setup
=============================

Audience
--------

This guide is for webhook administrators configuring inbound endpoints and
their relational rule rows in Odoo.

Create the endpoint
-------------------

When creating an inbound endpoint, start with the core record fields:

* ``path`` defines the immutable public URL segment under
  ``/webhooks/in/<path>``
* ``state`` controls whether the public route accepts traffic
* ``company_id`` always applies
* ``partner_id`` is optional and narrows visibility and ownership
* ``execution_user_id`` defines the internal user that accepted-request work
  and queued processing run as
* ``handler_id`` is the default inbound handler

Use ``draft`` while configuring. Switch to ``active`` only when the endpoint is
ready to accept traffic. ``archived`` keeps audit history visible but stops new
request matching.

Add value resolution rules
--------------------------

The ``Value Resolution`` page defines how inbound requests become structured
values.

Common source kinds are:

* ``header`` for a direct HTTP header
* ``header_param`` for structured header parameters
* ``payload_path`` for dotted JSON paths such as ``data.id``
* ``literal`` for fixed values
* ``body_sha256`` for raw body hashing
* ``computed`` for endpoint-provided computed methods

Use ``candidate_sequence`` and ``sequence`` to control fallback order and line
order. The same resolved key can have several candidate tiers.

Bind built-in semantics
-----------------------

The ``Semantic Bindings`` page connects resolved keys to built-in webhook
concepts. Common bindings include:

* ``delivery_id`` for exact-delivery deduplication
* ``event_id`` for business-event identity
* ``event_type`` and ``topic`` for downstream routing
* ``signature`` and ``signature_timestamp`` for HMAC validation
* ``idempotency_key`` when the upstream system provides an explicit idempotency
  value

Choose identity policies carefully
----------------------------------

Inbound endpoints make two different identity decisions:

``delivery_identity_policy``
  Identifies an exact delivery so duplicates can be rejected.

``replay_identity_policy``
  Links distinct deliveries of the same business event for audit and replay
  analysis.

Use ``delivery_id`` or ``idempotency_key`` when the upstream system provides a
stable identifier. Use ``body_sha256`` when you need a fallback deduplication
strategy and the payload itself is the best identity available.

Configure signatures when needed
--------------------------------

For signed providers, enable ``signature_verification_mode = hmac`` and then
configure:

* the shared secret, and optionally the secondary secret
* digest algorithm and encoding
* optional signature prefix
* timestamp format and freshness window
* signature message parts when the provider signs something other than the raw
  body

If no signature-part rows are configured, the raw request body is used as the
signed message.

Attach the handler
------------------

Attach a default handler when the endpoint should do more than store the event.

* Use a model-driven handler when operators should manage the logic with
  relational rules.
* Use a Python callback handler when a developer provides custom code in a
  business module.

Demo walkthroughs
-----------------

Use the demo records as examples:

* ``Demo Orders Endpoint`` shows resolved values from headers and payload paths.
* ``Demo Signed Partner Endpoint`` shows HMAC verification and partner scope.
* ``Demo Any JSON Store-Only Endpoint`` shows the minimal audit-only path.

See also
--------

* `Operator getting started <operator_getting_started.rst>`_
* `Operator operations <operator_operations.rst>`_
* `Developer inbound patterns <developer_inbound_patterns.rst>`_
