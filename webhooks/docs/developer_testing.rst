Developer Guide: Testing Integrations
=====================================

Audience
--------

This guide is for developers writing tests for modules that depend on the
webhooks addon.

Start with the shared test helpers
----------------------------------

``webhooks.tests.common.WebhookRuleTestCase`` is the main base class for addon
and integration tests. It provides fixture helpers such as:

* ``_create_handler()``
* ``_create_inbound_endpoint()``
* ``_create_outbound_endpoint()``
* ``_create_inbound_event()``
* ``_create_outbound_delivery()``
* ``_create_outbound_context_line()``

These helpers keep tests focused on behavior instead of boilerplate setup.

Inbound testing pattern
-----------------------

For inbound integrations, the normal pattern is:

1. create handler and endpoint
2. add sources, bindings, and rules
3. create an inbound event fixture
4. execute the handler or call ``process_event()``
5. assert record changes and rule execution evidence

Use ``test_inbound_model_driven_rules.py`` as the primary example for create,
update, upsert, and queue-outbound scenarios.

Outbound testing pattern
------------------------

For outbound integrations, the normal pattern is:

1. create outbound endpoint and optional handler
2. add header rules, payload rules, or outbound rules
3. create a delivery and context lines
4. call ``_build_request_data()``, ``execute_outbound()``, or
   ``process_delivery()``
5. assert request mutations, state changes, attempt records, and snapshots

Use ``test_outbound_model_driven_rules.py`` and
``test_webhook_outbound_delivery_processing.py`` as the main references.

Security and scope tests
------------------------

If your module depends on partner-aware visibility, use the existing security
test patterns as a reference. ``test_webhook_security_relational_models.py``
shows how scoped users should or should not see relational child records.

Validation flow
---------------

After changing docs or integration code:

* run the targeted test module first
* run repo hooks on the touched files
* run the addon install/test flow when the change affects broad behavior or
  packaging

The addon test suite is intentionally split by topic. Add new integration tests
to the narrowest existing module when possible.

See also
--------

* `Developer inbound patterns <developer_inbound_patterns.rst>`_
* `Developer outbound patterns <developer_outbound_patterns.rst>`_
* `Maintainer security and testing <maintainer_security_and_testing.rst>`_
