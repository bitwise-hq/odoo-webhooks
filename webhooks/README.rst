Webhooks
========

This addon provides a generic inbound and outbound webhook framework for Odoo.

Supported design
----------------

* inbound endpoints with public HTTP intake
* relational source lines, semantic bindings, and signature-part configuration
* relational inbound handler conditions, lookups, and assignments
* durable inbound event storage with idempotency and execution logs
* outbound endpoints with relational header and payload rules
* outbound deliveries with relational context lines and queued processing
* relational outbound handler conditions and assignments
* runtime request and response snapshots for auditability

Operator workflow
-----------------

* configure an inbound or outbound endpoint with company scope and,
	optionally, a partner scope
* define relational child rows for value resolution, signatures,
	header rules, payload rules, or delivery context
* attach a model-driven handler when inbound or outbound rule
	evaluation should mutate data or route processing
* review inbound events, outbound deliveries, attempts, and execution
	logs through the stored audit snapshots

JSON fields shown on inbound events and outbound deliveries are runtime evidence only.
The supported authoring path is relational configuration through the child rule and
config models.

Security model
--------------

* company rules apply to all webhook records
* optional partner scoping on handlers and endpoints cascades to
	relational child rows
* webhook operators have read-only access within their allowed partners
* webhook admins can manage webhook configuration across the full
	allowed company scope

Demo data
---------

The demo data installs:

* a company-scoped inbound orders endpoint with relational source and semantic binding rules
* a partner-scoped signed inbound endpoint with relational signature assembly
* a flexible JSON-value store-only endpoint
* a partner-scoped outbound loopback endpoint with relational header
	rules, payload rules, outbound handler rules, and seeded delivery
	context lines