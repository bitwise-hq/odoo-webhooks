Developer Guide: Inbound Patterns
=================================

Audience
--------

This guide is for developers creating inbound integrations with either
model-driven rules or a mix of model-driven setup and custom module code.

Programmatic endpoint setup
---------------------------

The core inbound records are the endpoint, source lines, semantic bindings, and
the handler.

.. code-block:: python

   handler = self.env["webhook.handler"].create(
       {
           "name": "Shop Orders",
           "code": "shop_orders",
           "direction": "inbound",
           "execution_mode": "model_driven",
           "company_id": self.env.company.id,
       }
   )

   endpoint = self.env["webhook.endpoint"].create(
       {
           "name": "Shop Orders Endpoint",
           "path": "shop-orders",
           "company_id": self.env.company.id,
           "execution_user_id": technical_user.id,
           "handler_id": handler.id,
           "delivery_identity_policy": "delivery_id",
           "replay_identity_policy": "event_id",
           "payload_contract": "json_object",
       }
   )

   self.env["webhook.endpoint.source"].create(
       {
           "endpoint_id": endpoint.id,
           "field_name": "delivery_id",
           "source_kind": "header",
           "header_name": "X-Delivery-Id",
       }
   )

   self.env["webhook.endpoint.semantic.binding"].create(
       {
           "endpoint_id": endpoint.id,
           "semantic_name": "delivery_id",
           "value_key": "delivery_id",
       }
   )

Use source lines to create reusable resolved keys first, then bind the keys you
need to built-in semantics.

Model-driven inbound rules
--------------------------

Model-driven handlers use these child models:

* ``webhook.handler.inbound.rule``
* ``webhook.handler.inbound.rule.condition``
* ``webhook.handler.inbound.rule.lookup``
* ``webhook.handler.inbound.rule.assignment``

Typical action patterns are:

* ``create_record`` when every event creates a new business record
* ``update_record`` when a lookup must already match
* ``upsert_record`` when the event may create or update
* ``queue_outbound`` when the inbound event should create an outbound delivery
* ``done``, ``retry``, and ``dead_letter`` for operational routing

Condition and assignment source kinds
-------------------------------------

Inbound conditions and assignments resolve values from:

* ``resolved_value``
* ``semantic_field``
* ``event_field``
* ``literal``

Lookups build a search domain. Assignments build either record field values or
outbound context values, depending on the target kind.

Example: upsert a partner
-------------------------

.. code-block:: python

   rule = self.env["webhook.handler.inbound.rule"].create(
       {
           "handler_id": handler.id,
           "name": "Upsert Partner",
           "action_type": "upsert_record",
           "target_model_name": "res.partner",
       }
   )

   self.env["webhook.handler.inbound.rule.condition"].create(
       {
           "rule_id": rule.id,
           "source_kind": "semantic_field",
           "source_expression": "topic",
           "operator": "equals",
           "expected_value": "partner.sync",
       }
   )

   self.env["webhook.handler.inbound.rule.lookup"].create(
       {
           "rule_id": rule.id,
           "target_field_name": "ref",
           "source_kind": "resolved_value",
           "source_expression": "external_ref",
       }
   )

   self.env["webhook.handler.inbound.rule.assignment"].create(
       {
           "rule_id": rule.id,
           "target_kind": "field",
           "target_expression": "name",
           "source_kind": "resolved_value",
           "source_expression": "customer_name",
       }
   )

Audit expectations
------------------

Inbound processing records the matched rule on the event and creates a
``webhook.inbound.rule.execution`` row. Use those records to assert behavior in
tests and to support operator troubleshooting.

See also
--------

* `Developer Python callbacks <developer_python_callbacks.rst>`_
* `Developer testing <developer_testing.rst>`_
* `Maintainer inbound pipeline <maintainer_inbound_pipeline.rst>`_
