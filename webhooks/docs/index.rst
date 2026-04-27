Webhooks Documentation
======================

This documentation is split by audience so each reader can move through the
final implementation without wading through unrelated detail.

Choose your track
-----------------

Operators
  Configure endpoints and handlers in Odoo, review inbound events, monitor
  outbound deliveries, and understand replay, retry, and audit workflows.

Developers
  Build integrations on top of the addon, implement Python callbacks,
  configure model-driven rules from custom modules, and test those
  integrations with the shared helpers.

Maintainers
  Understand the inbound and outbound pipelines, queue-job execution,
  partner-aware security rules, demo data, and the code-level boundaries used
  by the addon itself.

Shared principles
-----------------

* authored configuration is relational, not JSON-based
* runtime request and response JSON is preserved as audit evidence
* company rules always apply, and partner scope is optional but explicit
* execution users define the security context for background processing
* replay and reset are different operational choices and should be documented
  separately

Operator guides
---------------

* `Operator getting started <operator_getting_started.rst>`_
* `Operator inbound setup <operator_inbound_setup.rst>`_
* `Operator outbound setup <operator_outbound_setup.rst>`_
* `Operator operations <operator_operations.rst>`_

Developer guides
----------------

* `Developer getting started <developer_getting_started.rst>`_
* `Developer inbound patterns <developer_inbound_patterns.rst>`_
* `Developer Python callbacks <developer_python_callbacks.rst>`_
* `Developer outbound patterns <developer_outbound_patterns.rst>`_
* `Developer testing <developer_testing.rst>`_

Maintainer guides
-----------------

* `Maintainer architecture <maintainer_architecture.rst>`_
* `Maintainer inbound pipeline <maintainer_inbound_pipeline.rst>`_
* `Maintainer outbound pipeline <maintainer_outbound_pipeline.rst>`_
* `Maintainer security and testing <maintainer_security_and_testing.rst>`_

Reading order
-------------

* Operators should start with `Operator getting started <operator_getting_started.rst>`_.
* Developers should start with `Developer getting started <developer_getting_started.rst>`_.
* Maintainers should start with `Maintainer architecture <maintainer_architecture.rst>`_.

If you are unsure where you fit, start with the developer track. It bridges the
gap between day-to-day Odoo usage and addon internals.
