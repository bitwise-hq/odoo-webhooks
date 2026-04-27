Odoo Webhooks
=============

This repository contains the ``webhooks`` addon for Odoo 19.0.

The addon provides a generic inbound and outbound webhook framework for Odoo,
with relational configuration for endpoints, handlers, rules, security scope,
and operational audit records.

Repository contents
-------------------

* ``webhooks/``: the addon source code, demo data, tests, and end-user docs
* ``webhooks/docs/``: operator, developer, and maintainer guides
* ``.pre-commit-config.yaml``: repository quality checks used during local
  development and CI

Addon dependencies
------------------

The addon depends on:

* ``mail``
* ``queue_job``

When installing or testing this repository, make sure both this addon and the
required ``queue_job`` addon are available on the Odoo addons path.

Where to start
--------------

* `Addon README <webhooks/README.rst>`_
* `Documentation index <webhooks/docs/index.rst>`_
* `Operator getting started <webhooks/docs/operator_getting_started.rst>`_
* `Developer getting started <webhooks/docs/developer_getting_started.rst>`_
* `Maintainer architecture <webhooks/docs/maintainer_architecture.rst>`_

Development notes
-----------------

This repository is organized around a single addon. The repository-level
README is a landing page for GitHub and local checkout users, while the addon
README and the ``webhooks/docs`` tree hold the detailed functional and
technical documentation.

For local validation, run the repository pre-commit hooks and the addon test
flow used for OCA-style installs.
