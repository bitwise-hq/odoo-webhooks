Odoo Webhooks
=============

This repository contains the ``webhooks`` family of addons for Odoo 19.0.

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

Connector Glue install order
----------------------------

For connector-backed webhook integrations, install in this order:

1. ``bwt_connector_webhooks_core``
2. ``bwt_connector_webhooks_inbound`` (if inbound is needed)
3. ``bwt_connector_webhooks_outbound`` (if outbound is needed)

Concrete connector addons then seed endpoint records and link them to backend
records through ``connector_backend_ref``.

Documentation
-------------

Each addon ships documentation; framework addons include operator and developer
guides under ``readme/`` and Glue side addons include detailed README guides.

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

**Connector Webhooks - Glue Core** (``bwt_connector_webhooks_core/``)

* `Operator Guide <bwt_connector_webhooks_core/readme/OPERATOR_GUIDE.rst>`_ —
  what the connector layer is, linking endpoints to backends, troubleshooting.
* `Developer Guide <bwt_connector_webhooks_core/readme/DEVELOPER_GUIDE.rst>`_ —
  registering a backend, inbound and outbound mixins, required overrides,
  endpoint seeding.

**Connector Webhooks - Glue Inbound** (``bwt_connector_webhooks_inbound/``)

* `README <bwt_connector_webhooks_inbound/README.rst>`_ — inbound mixin
  contract, dependencies, backend linking flow, troubleshooting.

**Connector Webhooks - Glue Outbound** (``bwt_connector_webhooks_outbound/``)

* `README <bwt_connector_webhooks_outbound/README.rst>`_ — outbound mixin
  contract, multi-endpoint routing, dependencies, troubleshooting.

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

LGPL-3 - `GNU Lesser General Public License v3.0 <http://www.gnu.org/licenses/lgpl-3.0-standalone.html>`_.
