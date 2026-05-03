Developer Guide: Getting Started
================================

Audience
--------

This guide is for developers building business addons that depend on both
``connector`` and ``webhooks`` and need one connector backend to own webhook
configuration records.

When to use this addon
----------------------

Use the addon when your backend model needs to:

* expose linked inbound and outbound webhook records directly on the backend
* keep a relational back-reference from endpoints to the owning backend
* open linked endpoints from backend actions without duplicating generic code
* enforce that linked endpoints stay in the same company as the backend

What this addon adds
--------------------

On ``connector.backend``
  ``webhook_endpoint_id``, ``outbound_endpoint_id``, related handler fields,
  related route and target URL fields, and helper actions.

On ``webhook.inbound.endpoint`` and ``webhook.outbound.endpoint``
  ``connector_backend_ref`` plus uniqueness and company consistency checks.

What it does not add
--------------------

This addon does not:

* create handlers or endpoints by itself
* define business-specific templates, callbacks, or rules
* decide when a backend should provision or resync its webhook records

Those responsibilities stay in the consuming business addon.

Typical integration pattern
---------------------------

1. Add ``connector_webhooks`` to the business addon dependencies.
2. Inherit ``connector.backend`` on the business backend model.
3. Implement ``_sync_webhook_configuration()`` in the business addon.
4. Write ``connector_backend_ref`` on created inbound and outbound endpoints by
   calling ``_get_connector_backend_reference()``.
5. Reuse ``action_view_inbound_endpoint()`` and
   ``action_view_outbound_endpoint()`` instead of duplicating generic actions.

Minimal example
---------------

.. code-block:: python

   from odoo import models


   class StripeBackend(models.Model):
       _name = "stripe.backend"
       _inherit = "connector.backend"

       def _sync_webhook_configuration(self):
           self.ensure_one()
           inbound_endpoint = self.env["webhook.inbound.endpoint"].create(
               {
                   "name": f"{self.name} Inbound Endpoint",
                   "path": self.webhook_path,
                   "company_id": self.company_id.id,
                   "execution_user_id": self.webhook_execution_user_id.id,
                   "connector_backend_ref": self._get_connector_backend_reference(),
               }
           )
           self.write({"webhook_endpoint_id": inbound_endpoint.id})

The glue addon gives the backend model the ownership helpers. The business
addon still decides how handlers, endpoint rules, signatures, and outbound
configuration should be provisioned.

Stable concepts to learn first
------------------------------

* each endpoint model stores at most one link for a given backend reference
* the backend reference selection includes only concrete ``connector.backend``
  inheritors
* backend actions may trigger lazy provisioning by calling
  ``_sync_webhook_configuration()`` when the backend addon implements it
* endpoint and handler internals still belong to the main ``webhooks`` addon

Next steps
----------

* Continue to the main `Webhooks developer getting started <../../webhooks/docs/developer_getting_started.rst>`_
  guide for endpoint and handler concepts.
* Continue to `Webhooks inbound patterns <../../webhooks/docs/developer_inbound_patterns.rst>`_
  for inbound endpoint configuration.
* Continue to `Webhooks outbound patterns <../../webhooks/docs/developer_outbound_patterns.rst>`_
  for outbound delivery design.