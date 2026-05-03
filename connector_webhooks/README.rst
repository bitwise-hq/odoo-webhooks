Connector Webhooks
==================

This addon provides the relational glue between ``connector`` backends and the
``webhooks`` framework. It is designed for two audiences:

* developers building connector-backed webhook addons
* maintainers evolving the boundary between the connector and webhooks frameworks

Documentation map
-----------------

Start with the guide that matches your role:

* `Documentation index <docs/index.rst>`_
* `Developer getting started <docs/developer_getting_started.rst>`_
* `Maintainer architecture guide <docs/maintainer_architecture.rst>`_

Supported design
----------------

This addon is intentionally narrow:

* ``connector.backend`` gains linked inbound and outbound endpoint fields and
  helper actions
* inbound and outbound webhook endpoints gain an optional
  ``connector_backend_ref`` back-reference
* ownership stays relational and company-aware on both sides
* business addons remain responsible for provisioning handlers, endpoints,
  rules, and templates

The addon does not create webhook configuration on its own. Consuming backend
addons should implement their own sync or provisioning logic.

Core concepts
-------------

* ``webhook_endpoint_id`` and ``outbound_endpoint_id`` store the linked endpoint
  records on the backend
* ``inbound_handler_id`` and ``outbound_handler_id`` expose the linked handlers
  through related fields
* ``route_path`` and ``outbound_target_url`` surface the resolved endpoint URLs
  on the backend
* ``connector_backend_ref`` lets endpoints point back to the owning connector
  backend
* helper actions can open linked endpoint forms and may call
  ``_sync_webhook_configuration()`` when the backend addon provides it

Audience guide
--------------

Developers
  Use the developer guide to wire a connector backend to webhook endpoint
  ownership without duplicating the generic relationship layer.

Maintainers
  Use the maintainer guide to understand the addon boundary, invariants, and
  helper methods before changing the glue layer itself.

There is no separate operator track for this addon. Day-to-day endpoint setup,
delivery monitoring, and webhook processing behavior remain documented in the
main ``webhooks`` addon.

See `Documentation index <docs/index.rst>`_ for the full guide set.