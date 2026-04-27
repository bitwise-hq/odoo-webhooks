Developer Guide: Getting Started
================================

Audience
--------

This guide is for developers building business-module integrations on top of
the addon. It explains the stable concepts, workflows, and extension points you
need without dropping immediately into full maintainer detail.

When to use this addon
----------------------

Use the addon when you need Odoo to:

* receive public webhook traffic and store auditable inbound events
* route inbound traffic through relational rules or Python callbacks
* create durable outbound deliveries with retry, dead-letter, and replay
* keep configuration relational while preserving request and response evidence

Core developer model
--------------------

As a developer, you will usually work with these layers:

* ``webhook.endpoint`` for inbound configuration
* ``webhook.handler`` for execution strategy
* inbound rule families for model-driven business actions
* ``webhook.outbound.endpoint`` for outbound targets
* ``webhook.outbound.delivery`` and context lines for runtime outbound work

The addon deliberately separates configuration records from runtime audit
records. Your custom module should extend or consume those layers rather than
re-introducing authored JSON.

Demo-backed learning path
-------------------------

The shipped demo data is the best starting point:

* ``Demo Orders Endpoint`` shows an inbound create-or-update style flow.
* ``Demo Signed Partner Endpoint`` shows signature verification and partner
  scope.
* ``Demo Outbound Loopback Orders Endpoint`` shows outbound assembly and
  handler-driven mutation.

Stable concepts to learn first
------------------------------

* resolved values come from ``webhook.endpoint.source`` rows
* built-in semantics come from ``webhook.endpoint.semantic.binding`` rows
* handler direction and execution mode are separate decisions
* exact-delivery deduplication and replay grouping are separate identity
  decisions
* outbound request data is assembled before the outbound handler mutates it

Developer boundaries
--------------------

This track covers how to use the addon from your own modules. It does not go
deep into record-rule internals, queue-job registration details, or low-level
pipeline implementation. Those belong in the maintainer track.

Next steps
----------

* Continue to `Developer inbound patterns <developer_inbound_patterns.rst>`_
  for inbound rules and endpoint configuration.
* Continue to `Developer Python callbacks <developer_python_callbacks.rst>`_
  for custom-code handlers.
* Continue to `Developer outbound patterns <developer_outbound_patterns.rst>`_
  for outbound delivery design.
* Continue to `Developer testing <developer_testing.rst>`_ for test helpers and
  validation flows.
