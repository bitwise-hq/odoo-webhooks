Webhooks
========

This addon provides a relational inbound and outbound webhook framework for
Odoo. It is designed for three audiences:

* operators configuring and monitoring webhook traffic in Odoo
* developers building business-module integrations on top of the addon
* maintainers evolving the addon internals, security model, and test surface

Documentation map
-----------------

Start with the guide that matches your job:

* `Documentation index <docs/index.rst>`_
* `Operator getting started <docs/operator_getting_started.rst>`_
* `Developer getting started <docs/developer_getting_started.rst>`_
* `Maintainer architecture guide <docs/maintainer_architecture.rst>`_

Supported design
----------------

The supported configuration path is relational throughout the addon:

* inbound endpoints use source lines, semantic bindings, and signature parts
* inbound handlers use rule, condition, lookup, and assignment rows
* outbound endpoints use header rules and payload rules
* outbound deliveries use context lines and attempt history
* outbound handlers use rule, condition, and assignment rows

JSON fields shown on inbound events and outbound deliveries are runtime audit
evidence only. They are not the supported authoring surface.

Core concepts
-------------

* ``webhook.endpoint`` receives inbound HTTP traffic on an immutable public path
* ``webhook.outbound.endpoint`` defines where outbound deliveries are sent
* ``webhook.handler`` chooses between model-driven rules and Python callbacks
* source lines resolve raw request data into reusable keys
* semantic bindings map those keys to built-in webhook concepts such as
  delivery identity, event identity, signature, topic, and handler selection
* delivery identity and replay identity are separate decisions
* optional ``partner_id`` scope cascades from handlers and endpoints to their
  relational child rows

Audience guide
--------------

Operators
  Use the operator guides to configure endpoints, review inbound events,
  monitor outbound deliveries, and understand replay, reset, and queue actions.

Developers
  Use the developer guides to build integrations in custom Odoo modules,
  implement Python callback handlers, create deliveries programmatically, and
  test integrations with the shared webhook test helpers.

Maintainers
  Use the maintainer guides to understand the request and delivery pipelines,
  queue-job integration, partner-aware security rules, demo data strategy, and
  validation workflow for changes to the addon itself.

Demo scenarios
--------------

The demo data provides four reference scenarios that are reused throughout the
documentation:

* a company-scoped inbound orders endpoint
* a partner-scoped signed inbound endpoint
* a store-only endpoint that accepts any JSON value
* a partner-scoped outbound loopback endpoint with handler-driven mutations

See `Documentation index <docs/index.rst>`_ for the full guide set.

.. note::

   The documentation describes only the final relational implementation.
   Removed JSON authoring paths are intentionally not part of the supported
   workflow.