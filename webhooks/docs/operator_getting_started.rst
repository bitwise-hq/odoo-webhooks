Operator Guide: Getting Started
===============================

Audience
--------

This guide is for people using the addon inside Odoo to configure, monitor,
and troubleshoot inbound and outbound webhooks.

What you work with
------------------

Operators mainly work with four record types:

* inbound endpoints, which receive public webhook requests
* handlers, which define what business logic or model-driven rules run
* outbound endpoints, which define where outbound deliveries are sent
* inbound events and outbound deliveries, which provide the operational audit
  trail

Roles and scope
---------------

The addon separates webhook roles into operator and administrator behavior.

* Webhook operators can review webhook records inside their allowed partner
  scope.
* Webhook administrators can manage configuration across the allowed company
  scope.
* Optional partner scope on handlers and endpoints cascades to relational child
  records such as rules, conditions, lookups, assignments, header rules, and
  context lines.

Ask an administrator to set ``webhook_allowed_partner_ids`` on your user if you
should only see records for specific tenants or accounts.

Key terms
---------

Endpoint
  The inbound or outbound configuration record that defines the route or the
  destination.

Handler
  The logic layer attached to an endpoint. A handler runs either in
  model-driven mode or in Python callback mode.

Source line
  A relational rule that resolves a value from headers, payload paths,
  literals, hashes, or computed methods.

Semantic binding
  The mapping from a resolved key to a built-in webhook meaning such as
  ``delivery_id``, ``event_id``, ``signature``, or ``topic``.

Context line
  A named value stored on an outbound delivery so handler rules can mutate or
  route that delivery.

Attempt
  A single outbound HTTP send attempt, including request and response evidence.

Where to start in the demo data
-------------------------------

The demo records provide good examples for the live UI:

* ``Demo Orders Endpoint`` shows a company-scoped inbound configuration.
* ``Demo Signed Partner Endpoint`` shows a partner-scoped signed flow.
* ``Demo Any JSON Store-Only Endpoint`` shows the minimal audit-only case.
* ``Demo Outbound Loopback Orders Endpoint`` shows outbound header rules,
  payload rules, handler rules, and replay-ready deliveries.

Common workflow
---------------

1. Create or open an endpoint.
2. Set company scope, optional partner scope, and the execution user.
3. Define the relational child rows instead of editing raw JSON.
4. Attach a handler when the endpoint should do more than store audit data.
5. Review inbound events or outbound deliveries as traffic moves through the
   system.

Next steps
----------

* Continue to `Operator inbound setup <operator_inbound_setup.rst>`_ if you are
  configuring inbound webhooks.
* Continue to `Operator outbound setup <operator_outbound_setup.rst>`_ if you
  are configuring outbound sends.
* Continue to `Operator operations <operator_operations.rst>`_ if you mainly
  monitor, replay, or troubleshoot traffic.
