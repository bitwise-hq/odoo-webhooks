Maintainer Guide: Inbound Pipeline
==================================

Audience
--------

This guide is for maintainers working on the inbound request path.

Route entrypoint
----------------

Inbound traffic enters through ``WebhookController.inbound_webhook()`` on the
public route ``/webhooks/in/<endpoint_path>``.

The controller:

* reads the raw body and headers
* looks up the active endpoint by path under automated execution context
* delegates request intake to ``webhook.inbound.event._receive_webhook_request``
* translates validation exceptions into HTTP 400 or 403 responses
* returns HTTP 202 after durable event storage

Validation and event creation
-----------------------------

The endpoint layer is responsible for:

* payload-contract validation
* source resolution
* semantic extraction
* signature verification and freshness checks
* exact-delivery identity resolution
* replay identity resolution

Accepted and rejected requests both become durable audit records. Rejected
events are stored for auditability rather than retried as normal processing
failures.

Queued processing
-----------------

``WebhookInboundEvent._queue_processing()`` schedules ``process_event()`` with
queue-job identity based on the event id. Execution runs under the event's
execution user, not the operator clicking the button.

Handler execution
-----------------

``process_event()`` distinguishes four cases:

* no handler: mark done and keep the event as stored-only evidence
* Python callback handler: delegate to ``execute_inbound()``
* model-driven handler: delegate to ``_execute_model_driven_handler()``
* retry or failure paths: update state and preserve processing evidence

Model-driven rules are evaluated in sequence order. The first full condition
match wins. Each matched rule produces a ``webhook.inbound.rule.execution`` row.

Result contract
---------------

Inbound handler results are consumed by ``process_event()``. Supported dict
statuses are:

* ``done``
* ``received``
* ``retry`` with optional ``seconds``
* ``dead_letter``

``note`` or ``message`` becomes the processing note. ``matched_rule_id`` is
stored when present.

Non-obvious boundaries
----------------------

* delivery identity and replay identity solve different problems
* event snapshots are audit evidence and should not be treated as authored
  config
* retry raises ``RetryableJobError`` instead of silently leaving the event in a
  retryable state
* rejected events and failed processed events are different operational classes

See also
--------

* `Maintainer architecture <maintainer_architecture.rst>`_
* `Developer inbound patterns <developer_inbound_patterns.rst>`_
