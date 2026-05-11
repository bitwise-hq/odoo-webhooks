Odoo Webhooks
=============

This repository contains the ``webhooks`` family of addons for Odoo 18.0.

The addon provides a generic inbound and outbound webhook framework for Odoo,
with relational configuration for endpoints, handlers, rules, security scope,
and operational audit records.

Repository contents
-------------------

* ``bwt_webhooks_core/``: the core handler registry, services, security, and
  shared primitives.
* ``bwt_webhooks_inbound/``: the inbound endpoint gateway with signature
  verification, replay protection, and rule-based event processing.
* ``bwt_webhooks_outbound/``: the outbound delivery engine with HTTP dispatch,
  retries, and per-attempt audit records.
* ``bwt_connector_webhooks_core/``: shared base and mixins for connector
  backends that own webhook endpoints.
* ``bwt_connector_webhooks_inbound/``: inbound side mixin for connector backends.
* ``bwt_connector_webhooks_outbound/``: outbound side mixin for connector backends.
* ``.pre-commit-config.yaml``: repository quality checks used during local
  development and CI.

Addon dependencies
------------------

The addon stack depends on:

* ``mail``
* ``queue_job``
* ``connector`` (required by the ``bwt_connector_webhooks_*`` addons)

When installing or testing this repository, make sure the required addons are
available on the Odoo addons path.

Documentation
-------------

Each addon ships its own operator and developer guides under its ``readme/``
folder.

**Webhooks Core** (``bwt_webhooks_core/``)

* `Operator Guide <bwt_webhooks_core/readme/OPERATOR_GUIDE.rst>`_ — installation,
  access roles, creating handlers, troubleshooting.
* `Developer Guide <bwt_webhooks_core/readme/DEVELOPER_GUIDE.rst>`_ — data model,
  handler execution modes, service layer, extension points.

**Webhooks Inbound** (``bwt_webhooks_inbound/``)

* `Operator Guide <bwt_webhooks_inbound/readme/OPERATOR_GUIDE.rst>`_ — endpoint
  setup, signature verification, identity policies, event monitoring.
* `Developer Guide <bwt_webhooks_inbound/readme/DEVELOPER_GUIDE.rst>`_ — inbound
  pipeline lifecycle, model-driven rule contract, value extraction, extension.

**Webhooks Outbound** (``bwt_webhooks_outbound/``)

* `Operator Guide <bwt_webhooks_outbound/readme/OPERATOR_GUIDE.rst>`_ — endpoint
  setup, header/payload rules, delivery monitoring, retries.
* `Developer Guide <bwt_webhooks_outbound/readme/DEVELOPER_GUIDE.rst>`_ — outbound
  pipeline, delivery state machine, context lines, transport layer.

**Connector Webhooks Core** (``bwt_connector_webhooks_core/``)

* `Operator Guide <bwt_connector_webhooks_core/readme/OPERATOR_GUIDE.rst>`_ —
  what the connector layer is, linking endpoints to backends, troubleshooting.
* `Developer Guide <bwt_connector_webhooks_core/readme/DEVELOPER_GUIDE.rst>`_ —
  registering a backend, inbound and outbound mixins, required overrides,
  endpoint seeding.

Development notes
-----------------

This repository is organized around a small addon family. The repository-level
README is a landing page for GitHub and local checkout users. Each addon's
``readme/`` folder holds the functional and technical documentation.

For local validation, run the repository pre-commit hooks and the addon test
flow used for OCA-style installs.

Contributors
------------

* Bitwise Technologies LLC
* Youssef Egla

License
-------

Proprietary - `Odoo Proprietary License v1.0 (OPL-1) <https://www.odoo.com/documentation/user/legal/licenses.html>`_.
