Webhooks Outbound — Operator Guide
=====================================

This guide covers the outbound delivery engine: creating and configuring outbound
endpoints, triggering deliveries, monitoring attempts, and handling failures.

Prerequisites
-------------

Install ``bwt_webhooks_outbound`` after ``bwt_webhooks_core`` and ``queue_job``
are in place. At least one handler with **Direction = Outbound** must exist before
creating an endpoint that uses a handler.

Creating an Outbound Endpoint
------------------------------

Go to **Webhooks → Outbound → Endpoints → New**.

Required fields:

- **Name** — human-readable label.
- **Code** — stable, unique technical identifier used by connector addons and
  programmatic dispatch (lowercase slug; no spaces).
- **HTTP Method** — ``POST`` (default), ``PUT``, ``PATCH``, or ``DELETE``.
- **Request Body Mode** — controls how the payload is encoded:

  - ``JSON`` — ``application/json``; default for REST APIs.
  - ``Form URL Encoded`` — ``application/x-www-form-urlencoded``.
  - ``Multipart`` — ``multipart/form-data``.

- **Target Path** — the URL path, optionally with ``{token}`` placeholders
  resolved from delivery context lines (e.g. ``/v1/orders/{order_id}``).
- **Company** — defaults to the current company.

Target Hostname
~~~~~~~~~~~~~~~

Set **Target Hostname** to the absolute base URL including the scheme (e.g.
``https://api.example.com``). Leave it blank when a connector addon resolves
the hostname dynamically via ``_get_outbound_api_base_url``.

Handler (optional)
~~~~~~~~~~~~~~~~~~~

Attach an outbound handler to intercept deliveries before the HTTP request is
sent. The handler can mutate the payload, retry, cancel, or dead-letter the
delivery before the HTTP call is made.

Header and Payload Rules
~~~~~~~~~~~~~~~~~~~~~~~~~

Use the **Headers** and **Payload** tabs to configure rules that build the
outgoing request:

- **Header rules** — add or override request headers. Supports literal values
  and context-line token references.
- **Payload rules** — construct or override the request body using field paths
  and value mappings.
- **Context lines** — key/value pairs attached to a delivery at queue time;
  referenced in header and payload rules and path tokens via ``{key}`` syntax.

Endpoint States
~~~~~~~~~~~~~~~~

- **Draft** — endpoint configured but deliveries are not dispatched.
- **Active** — endpoint is live; deliveries can be queued and dispatched.
- **Archived** — endpoint inactive; existing delivery records remain in audit
  history but no new deliveries can be queued.

Monitoring Deliveries
----------------------

Go to **Webhooks → Outbound → Deliveries** to see all deliveries.

Delivery lifecycle states:

- **Draft** — created but not yet queued.
- **Queued** — waiting for the background worker.
- **Processing** — background job is running.
- **Done** — HTTP request sent and accepted by the target.
- **Error** — an exception occurred or the target returned a non-success
  response code.
- **Dead Letter** — permanently failed after exhausting retries or explicitly
  dead-lettered; requires manual review.
- **Canceled** — cancelled before dispatch.

Click a delivery record to open its **Attempts** tab, which lists every HTTP
request made with the response status code, headers, and body.

Retries and Dead-Letter
------------------------

To retry a delivery in **Error** or **Dead Letter** state:

1. Open the delivery record.
2. Click **Reset to Draft** to move it back to the ``draft`` state.
3. Click **Queue** (or trigger re-queueing from your business flow) to
   re-enqueue the delivery.

To permanently close a failed delivery without retrying, use **Action →
Dead Letter** from the delivery form.

Troubleshooting Checklist
--------------------------

- **401 / authentication failures**: ensure the connector backend is active and
  the API key or secret field is populated (see the connector addon docs).
- **Target not reachable**: verify **Target Hostname** is correct and the Odoo
  server can reach the target host on the configured port.
- **Deliveries stuck in Queued**: confirm the ``queue_job`` worker is running
  and the job channel is not paused or at capacity.
- **Payload shape wrong**: open a delivery attempt and inspect the **Request
  Body** snapshot to compare the actual payload against the expected format.
- **Path token not resolved**: ensure the delivery's context lines contain a
  key matching the ``{token}`` placeholder in **Target Path**.
