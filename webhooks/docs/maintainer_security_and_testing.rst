Maintainer Guide: Security and Testing
======================================

Audience
--------

This guide is for maintainers working on security boundaries, validation, demo
data, and regression coverage.

Security model
--------------

The addon combines company-aware ownership with optional partner-aware scope.

Important rules:

* company rules apply to all webhook models
* partner scope is optional and inherited by relational child models
* webhook operators are read-only within allowed partner scope
* webhook administrators have the configuration and management authority needed
  for webhook execution

The user-visible partner filter comes from ``res.users.webhook_allowed_partner_ids``.

Execution users
---------------

Inbound and outbound endpoints require execution users. Background processing
runs as these users rather than the clicking operator. This is critical for:

* predictable business permissions
* audit clarity
* avoiding accidental superuser behavior during normal webhook processing

Testing surfaces
----------------

The current suite is split by behavior. Important anchors include:

* controller tests
* inbound model-driven rule tests
* endpoint source and signature tests
* inbound event processing tests
* outbound model-driven rule tests
* outbound delivery lifecycle and processing tests
* partner-aware security tests for relational child models

``tests/common.py`` provides the standard fixture factories for handlers,
endpoints, events, deliveries, and context lines.

Demo data role
--------------

The demo data is not just sample content. It is also the canonical narrative
surface for the documentation. Keep it aligned with:

* operator workflows
* developer examples
* supported relational configuration only

Validation workflow
-------------------

For documentation and behavior changes, the normal maintainer workflow is:

1. run the narrowest affected tests first
2. run repo hooks on touched files
3. run the addon install/test flow when packaging, README rendering, or broad
   behavior changed
4. confirm operator-visible flows in Odoo when views or security changed

When security changes land, update both the record rules and the focused
security regression tests.

Non-obvious guardrails
----------------------

* do not reintroduce authored JSON configuration paths
* keep runtime snapshots as evidence, not editable configuration
* preserve partner-aware child-row inheritance on new relational models
* prefer narrow tests and explicit queue or audit assertions when changing the
  pipelines

See also
--------

* `Maintainer architecture <maintainer_architecture.rst>`_
* `Developer testing <developer_testing.rst>`_
