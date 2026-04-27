Developer Guide: Outbound Patterns
==================================

Audience
--------

This guide is for developers who create outbound integrations, deliveries, and
handler logic on top of the addon.

Create an outbound endpoint
---------------------------

``webhook.outbound.endpoint`` defines the transport defaults: target host,
path, HTTP method, timeout, company scope, optional partner scope, execution
user, and optional outbound handler.

Add relational header and payload rules to shape the base request. These rules
are resolved before any outbound handler mutates the request.

Create deliveries programmatically
----------------------------------

The common flow is:

1. create a delivery for the endpoint
2. add context lines if the delivery needs runtime values
3. queue the delivery

.. code-block:: python

   delivery = self.env["webhook.outbound.delivery"].create(
       {
           "name": "Partner Sync",
           "endpoint_id": outbound_endpoint.id,
       }
   )

   self.env["webhook.outbound.delivery.context.line"].create(
       {
           "delivery_id": delivery.id,
           "key_name": "partner_ref",
           "source_kind": "literal",
           "literal_value": partner.ref,
       }
   )

   delivery.action_queue_delivery()

Request assembly order
----------------------

Outbound processing follows this order:

1. build the base request from endpoint header rules and payload rules
2. resolve context lines into named values
3. evaluate the outbound handler and matching rule
4. apply any returned URL, method, header, or payload mutations
5. persist the final request snapshot and create an attempt record

This means endpoint rules provide defaults, while handlers provide conditional
runtime overrides.

Model-driven outbound rules
---------------------------

Outbound handlers use these child models:

* ``webhook.handler.outbound.rule``
* ``webhook.handler.outbound.rule.condition``
* ``webhook.handler.outbound.assignment``

Rule conditions can inspect delivery fields, endpoint fields, company values,
partner values, context keys, and request fields. Assignment targets can mutate
the request URL or method, add headers, or write into payload paths.

Operational result patterns
---------------------------

Outbound rule or callback results can ask the processor to:

* send the request
* cancel the delivery
* dead-letter the delivery
* retry the delivery after a delay

Use ``Create Replay Delivery`` when you need a new audited resend row. Use
``Reset to Draft`` only when the same delivery record should be reused.

Debugging support
-----------------

Developers should inspect these records during integration work:

* delivery request and response snapshots
* matched outbound rule
* attempt history
* replay lineage
* queue job state if a delivery never moved past ``queued``

See also
--------

* `Developer Python callbacks <developer_python_callbacks.rst>`_
* `Developer testing <developer_testing.rst>`_
* `Maintainer outbound pipeline <maintainer_outbound_pipeline.rst>`_
