Developer Guide: Python Callbacks
=================================

Audience
--------

This guide is for developers who need custom logic that is not a good fit for
model-driven rules alone.

Handler configuration
---------------------

Set these handler fields when using Python callbacks:

* ``direction`` to ``inbound`` or ``outbound``
* ``execution_mode`` to ``python``
* ``python_model_name`` to the technical model name
* ``python_method_name`` to the method called by the handler

The method must exist, or the handler raises a validation error when it runs.

Inbound callback contract
-------------------------

Inbound Python callbacks receive the ``webhook.inbound.event`` record.

.. code-block:: python

   import json

   from odoo import models


   class SaleOrder(models.Model):
       _inherit = "sale.order"

       def webhook_process_order(self, event):
           payload = json.loads(event.payload_json or "{}")
           customer_name = event.get_resolved_value("customer_name")
           payload.setdefault("meta", {})["handled_by"] = "sale.order"
           return {
               "status": "done",
               "note": f"Processed {customer_name}",
           }

Supported inbound result shapes are those consumed by ``process_event``:

* ``{"status": "done"}``
* ``{"status": "received"}`` to leave the event queued again
* ``{"status": "retry", "seconds": 30}`` to request queue retry
* ``{"status": "dead_letter"}`` to stop and mark the event accordingly
* ``False`` to move the event back to ``received``

If you return a dict, ``note`` or ``message`` is stored as the processing note.

Outbound callback contract
--------------------------

Outbound Python callbacks receive the ``webhook.outbound.delivery`` record.

.. code-block:: python

   import json

   from odoo import models


   class ResPartner(models.Model):
       _inherit = "res.partner"

       def webhook_prepare_partner_push(self, delivery):
           payload = json.loads(delivery.payload_json or "{}")
           payload.setdefault("meta", {})["source"] = "custom"
           return {
               "status": "send",
               "payload": payload,
               "headers": {"X-Custom": "partner-sync"},
           }

Supported outbound result fields are those consumed by ``process_delivery`` and
``_apply_handler_result``:

* ``status`` with ``send``, ``cancel``, ``dead_letter``, or ``retry``
* ``note`` or ``message``
* ``seconds`` for retry delay
* ``target_url``
* ``http_method``
* ``headers``
* ``payload``

Best practices
--------------

* Treat event and delivery snapshots as immutable evidence.
* Use ``get_resolved_value()`` and stored fields instead of re-parsing request
  data whenever possible.
* Raise clear business exceptions for invalid data so the audit trail remains
  meaningful.
* Return explicit status dictionaries rather than relying on implicit behavior.
* Keep callback logic in your business module, not in ad-hoc monkey patches.

When to choose callbacks
------------------------

Choose Python callbacks when:

* you need cross-model orchestration that is awkward to express in rules
* business validation requires custom code
* you must reuse complex domain logic already implemented in a module

Choose model-driven rules when operators should remain able to inspect and
adjust the behavior without code changes.

See also
--------

* `Developer inbound patterns <developer_inbound_patterns.rst>`_
* `Developer outbound patterns <developer_outbound_patterns.rst>`_
* `Maintainer architecture <maintainer_architecture.rst>`_
