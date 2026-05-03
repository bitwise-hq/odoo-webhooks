Maintainer Guide: Architecture
==============================

Audience
--------

This guide is for maintainers changing ``connector_webhooks`` itself rather
than a consuming business addon.

System overview
---------------

This addon is a boundary layer between two existing frameworks:

Connector side
  ``connector.backend`` gains relational links, helper fields, and helper
  actions for linked webhook records.

Webhooks side
  inbound and outbound endpoints gain an optional backend reference plus
  ownership constraints.

Business-addon side
  consuming addons still own provisioning, synchronization, templates,
  callbacks, and business-specific rules.

Core model families
-------------------

Backend extension
  ``connector.backend`` with ``webhook_endpoint_id``, ``outbound_endpoint_id``,
  ``inbound_handler_id``, ``outbound_handler_id``, ``route_path``, and
  ``outbound_target_url``.

Endpoint back-references
  ``webhook.inbound.endpoint`` and ``webhook.outbound.endpoint`` with
  ``connector_backend_ref``.

View surface
  inherited endpoint views that show the owning backend reference on forms and
  lists.

Key invariants
--------------

* a backend can own at most one inbound endpoint and one outbound endpoint
* endpoint company must match backend company when the backend exposes
  ``company_id``
* only concrete ``connector.backend`` inheritors appear in the reference
  selection
* the glue addon never provisions webhook records by itself
* helper actions may attempt lazy sync only by calling a backend-provided
  ``_sync_webhook_configuration()`` method

Important entrypoints
---------------------

* ``ConnectorBackend._selection_connector_backend_models()``
* ``ConnectorBackend._get_connector_backend_reference()``
* ``ConnectorBackend._ensure_webhook_link()``
* ``ConnectorBackend.action_view_inbound_endpoint()``
* ``ConnectorBackend.action_view_outbound_endpoint()``
* ``WebhookInboundEndpoint._check_connector_backend_company()``
* ``WebhookOutboundEndpoint._check_connector_backend_company()``

Responsibility split
--------------------

``connector_webhooks``
  owns relational ownership, navigation helpers, and generic company checks.

``webhooks``
  owns inbound and outbound processing, handlers, rules, and audit models.

Consuming backend addons
  own configuration templates, sync policies, and business callback logic.

Validation flow
---------------

After changing the glue addon itself:

* run a narrow syntax or diagnostics check on the touched models and views
* run a focused consuming-addon install or test flow when the backend contract
  changes
* verify that backend actions still open the expected endpoint forms

See also
--------

* `Webhooks maintainer architecture <../../webhooks/docs/maintainer_architecture.rst>`_
* `Webhooks developer getting started <../../webhooks/docs/developer_getting_started.rst>`_