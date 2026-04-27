Maintainer Guide: Outbound Pipeline
===================================

Audience
--------

This guide is for maintainers working on outbound delivery execution and audit
behavior.

Delivery lifecycle
------------------

``webhook.outbound.delivery`` moves through these main states:

* ``draft``
* ``queued``
* ``processing``
* ``done``
* ``error``
* ``dead_letter``
* ``canceled``

``action_queue_delivery()`` writes runtime execution user information and
schedules ``process_delivery()`` with a stable queue-job identity key.

Request assembly
----------------

The outbound request is assembled in layers:

1. endpoint defaults from header rules and payload rules
2. per-delivery context values
3. outbound handler rule evaluation
4. result application through ``_apply_handler_result()``
5. durable request snapshot storage on the delivery and attempt row

This layering is the core outbound invariant. Endpoint rules define stable
defaults. Handler rules or callbacks define conditional runtime behavior.

Handler evaluation
------------------

``_execute_model_driven_handler()`` sorts active outbound rules by sequence and
selects the first rule whose conditions all match.

Assignments can target:

* request metadata such as URL or HTTP method
* request headers
* payload paths

The returned result is then interpreted by ``process_delivery()``.

Result contract
---------------

Outbound handler results may request:

* ``send``
* ``cancel``
* ``dead_letter``
* ``retry`` with optional ``seconds``

They may also override:

* ``target_url``
* ``http_method``
* ``headers``
* ``payload``

Attempt and response evidence
-----------------------------

Each send attempt creates a ``webhook.outbound.delivery.attempt`` row. The
delivery stores the latest effective request snapshot and response summary, but
the attempt rows are the detailed transport log.

Client-side HTTP failures move to ``dead_letter``. Transport failures and
server-side failures are retriable through queue-job behavior.

Replay behavior
---------------

``action_create_replay_delivery()`` copies the delivery into a new draft row and
links it through ``replayed_from_delivery_id``. This preserves the audit trail
instead of mutating the original completed delivery.

See also
--------

* `Maintainer architecture <maintainer_architecture.rst>`_
* `Developer outbound patterns <developer_outbound_patterns.rst>`_
