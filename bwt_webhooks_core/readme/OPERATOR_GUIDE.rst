Webhooks Core — Operator Guide
==============================

This guide covers the shared foundation of the webhook framework: installing the
addon stack, assigning access roles, and creating handler records that both the
inbound and outbound gateway addons depend on.

Prerequisites
-------------

Install the following addons in order:

1. ``queue_job`` — background job execution engine (OCA connector queue).
2. ``bwt_webhooks_core`` — shared handler registry and services.
3. ``bwt_webhooks_inbound`` (optional) — inbound endpoint gateway.
4. ``bwt_webhooks_outbound`` (optional) — outbound delivery engine.

Confirm the ``queue_job`` worker process is active on the server before
routing live traffic through any endpoint.

Access Roles
------------

Navigate to **Settings → Users & Companies → Users**, open a user record, and
locate the **Webhooks** privilege under the access rights tab.

- **Operator** — view events, deliveries, and audit records; trigger reprocess
  and dead-letter actions on individual records.
- **Administrator** — full read/write on all webhook configuration (handlers,
  endpoints, rules, signature parts); implies Operator.

Odoo system administrators receive the **Administrator** role automatically.

Creating a Handler
------------------

A handler defines *how* inbound events or outbound deliveries are processed.
It is the shared execution definition consumed by both gateway addons.

Go to **Webhooks → Handlers → New** and fill in:

- **Name** — human-readable label.
- **Code** — stable, unique technical identifier (lowercase slug; no spaces).
- **Direction** — ``Inbound`` for events, ``Outbound`` for deliveries.
- **Execution Mode** — choose one:

  - **Model Driven** — configure rule rows directly on the handler form;
    no Python code required.
  - **Python Callback** — the framework calls a specific method on a specific
    Odoo model at processing time; requires **Python Model** and
    **Python Method** to be set.

- **Company** — defaults to the current company.

Save the handler. It is now available to attach to inbound endpoints or
outbound endpoint configurations.

Python Callback Setup
~~~~~~~~~~~~~~~~~~~~~

When **Python Callback** is selected:

1. Set **Python Model** to the technical model name (e.g. ``sale.order``).
2. Set **Python Method** to the method that will be called
   (e.g. ``handle_webhook_event``).

Both fields are required; the handler form enforces this before saving.

Archiving Handlers
~~~~~~~~~~~~~~~~~~

Archived handlers remain visible in historical audit records but are no longer
selectable for new work. Use **Action → Archive** from the handler list or form.

Troubleshooting Checklist
-------------------------

- **Handler not selectable on an inbound endpoint**: verify **Direction** is
  set to ``Inbound``.
- **Handler not selectable on an outbound endpoint**: verify **Direction** is
  set to ``Outbound``.
- **Python callback raises "method not found"**: confirm the addon that defines
  the model is installed and the method name is spelled correctly.
- **Jobs are not processing**: check that the ``queue_job`` worker is running
  and that no job channel is paused or at capacity.
- **Company mismatch errors**: the handler, endpoint, and all target records
  must share the same company.
