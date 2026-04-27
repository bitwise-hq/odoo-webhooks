Operator Guide: Outbound Setup
==============================

Audience
--------

This guide is for webhook administrators configuring outbound endpoints and the
relational rules that shape outbound requests.

Create the outbound endpoint
----------------------------

An outbound endpoint defines where deliveries are sent and under what security
context they run.

Configure these fields first:

* ``http_method``
* ``target_hostname``
* ``target_path``
* ``timeout_seconds``
* ``company_id`` and optional ``partner_id``
* ``execution_user_id``
* optional outbound ``handler_id``

Like inbound endpoints, outbound endpoints move through ``draft``, ``active``,
and ``archived``. Keep the endpoint in ``draft`` while you are still editing
rules.

Define header rules
-------------------

The ``Header Rules`` page builds default outbound headers with relational rows.

Common source kinds include:

* ``literal`` for fixed values
* ``context_key`` for values stored on the delivery
* ``delivery_field`` for delivery metadata
* ``endpoint_field`` for endpoint metadata
* ``company_field`` and ``partner_field`` for scoped business information

Use these rows for stable defaults such as source markers, API version headers,
and routing metadata.

Define payload rules
--------------------

The ``Payload Rules`` page uses free-form target paths such as ``data.id`` or
``meta.company``. Each row writes one value into the assembled payload.

Use payload rules for:

* fixed metadata
* delivery-derived values
* company and partner information
* values injected through delivery context lines

Choose the outbound handler strategy
------------------------------------

Attach an outbound handler when the request must be changed after the endpoint
defaults have been assembled.

Model-driven outbound handlers can:

* match on context, request, or delivery state
* send, cancel, dead-letter, or retry a delivery
* override request URL or method
* mutate headers and payload values

Python callback handlers are available for module-specific custom logic. See
the developer guide before enabling them.

Use the loopback demo
---------------------

``Demo Outbound Loopback Orders Endpoint`` is the reference outbound example.
It combines:

* header rules from literals and context keys
* payload rules using nested target paths
* a partner-scoped outbound handler
* a seeded delivery with context lines ready for replay and debugging

Activation checklist
--------------------

Before activating an outbound endpoint, confirm that:

* the execution user has the needed business permissions
* header rules and payload rules cover the target system contract
* handler direction is ``outbound``
* handler execution mode matches your intended design
* the endpoint has a meaningful partner scope when tenant isolation matters

See also
--------

* `Operator operations <operator_operations.rst>`_
* `Developer outbound patterns <developer_outbound_patterns.rst>`_
* `Developer Python callbacks <developer_python_callbacks.rst>`_
