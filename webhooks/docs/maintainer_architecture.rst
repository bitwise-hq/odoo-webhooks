Maintainer Guide: Architecture
==============================

Audience
--------

This guide is for maintainers changing the addon itself rather than consuming it
from a business module.

System overview
---------------

The addon has two main pipelines:

Inbound
  Public HTTP request -> inbound endpoint lookup -> request validation ->
  durable inbound event -> queued processing -> handler execution -> rule
  execution evidence.

Outbound
  Delivery creation -> queue submission -> request assembly -> outbound handler
  evaluation -> HTTP send attempt -> durable attempt and response evidence.

Core model families
-------------------

Configuration models
  ``webhook.endpoint``, ``webhook.endpoint.source``,
  ``webhook.endpoint.semantic.binding``,
  ``webhook.endpoint.signature.part``, ``webhook.handler``,
  ``webhook.outbound.endpoint``, and the relational child rule models.

Runtime models
  ``webhook.inbound.event``, ``webhook.inbound.rule.execution``,
  ``webhook.outbound.delivery``, ``webhook.outbound.delivery.context.line``, and
  ``webhook.outbound.delivery.attempt``.

Security surface
  webhook groups, partner-aware record rules, company ownership, and execution
  user constraints.

Key invariants
--------------

* authored configuration is relational only
* runtime JSON remains as audit evidence
* company scope is always enforced
* partner scope is optional but explicit and queryable on child records
* handler direction and execution mode are separate decisions
* replay creates new delivery lineage rather than mutating the original send

Important entrypoints
---------------------

* ``WebhookController.inbound_webhook()``
* ``WebhookHandler.execute_inbound()``
* ``WebhookHandler.execute_outbound()``
* ``WebhookInboundEvent.process_event()``
* ``WebhookOutboundDelivery.process_delivery()``

How the docs are split
----------------------

* operator guides explain the UI and operational workflow
* developer guides explain stable integration patterns and callback contracts
* maintainer guides explain the internal flow, boundaries, and validation
  responsibilities

Continue to the pipeline guides for the implementation details.

See also
--------

* `Maintainer inbound pipeline <maintainer_inbound_pipeline.rst>`_
* `Maintainer outbound pipeline <maintainer_outbound_pipeline.rst>`_
* `Maintainer security and testing <maintainer_security_and_testing.rst>`_
