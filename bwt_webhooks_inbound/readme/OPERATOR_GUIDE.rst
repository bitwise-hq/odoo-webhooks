Webhooks Inbound — Operator Guide
==================================

This guide covers the inbound gateway: creating and configuring inbound endpoints,
monitoring events, and handling failures.

Prerequisites
-------------

Install ``bwt_webhooks_inbound`` after ``bwt_webhooks_core`` and ``queue_job``
are in place. At least one handler with **Direction = Inbound** must exist before
creating an endpoint.

Creating an Inbound Endpoint
-----------------------------

Go to **Webhooks → Inbound → Endpoints → New**.

Required fields:

- **Name** — human-readable label.
- **Path** — URL path suffix appended to the webhook base URL (e.g.
  ``/webhooks/my-service``). Must be unique across all endpoints.
- **Handler** — select a handler with **Direction = Inbound**.
- **Company** — defaults to the current company.

Save the record. The endpoint is immediately active and ready to receive
requests at the configured path.

Signature Verification
~~~~~~~~~~~~~~~~~~~~~~~

Under the **Signature** tab:

- **Signature Mode** — choose ``None`` (no verification) or ``Shared Secret
  HMAC`` (recommended for production).
- When HMAC is selected, configure:

  - **Digest** — ``SHA256`` is recommended; ``SHA1`` and ``SHA512`` are also
    supported.
  - **Encoding** — ``Hex`` or ``Base64``, depending on the upstream provider.
  - **Primary Secret** — the shared secret from the upstream provider.
  - **Secondary Secret** — optional rotation secret; valid during key rotation.
  - **Signature Parts** — define which header values and payload fragments are
    concatenated to build the signed message. Order matters and must match the
    upstream provider specification.
  - **Signature Header** — the request header that carries the signature value
    (e.g. ``X-Signature-256``).
  - **Signature Prefix** — optional prefix the provider prepends to the value
    (e.g. ``sha256=``); it is stripped before comparison.

Identity and Replay Policies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Under the **Identity** tab:

- **Delivery Identity Policy** — controls deduplication on receipt (the "same
  request" check):

  - ``Delivery Identity`` — a header-carried delivery ID.
  - ``Explicit Idempotency Key`` — a header-carried idempotency key.
  - ``Raw Body SHA256`` — hash of the raw request body.

- **Replay Identity Policy** — controls business-event-level deduplication (the
  "same business event" check):

  - ``None`` — no replay protection.
  - ``Business Event Identity`` — a field-path extracted event ID.
  - ``Explicit Idempotency Key`` — a header-carried idempotency key.

Timestamp Validation
~~~~~~~~~~~~~~~~~~~~~

Enable timestamp validation under the **Identity** tab to reject stale or
future-dated requests:

- **Timestamp Header** — the request header that carries the timestamp value.
- **Timestamp Format** — ``Unix Seconds``, ``Unix Milliseconds``, or
  ``ISO 8601``.
- **Max Age (seconds)** — requests older than this value are rejected.
- **Max Future Skew (seconds)** — requests dated this far ahead are rejected.

Monitoring Events
-----------------

Go to **Webhooks → Inbound → Events** to see all received events.

Event lifecycle states:

- **Received** — event stored; not yet processed.
- **Processing** — background job is running.
- **Done** — processing completed successfully.
- **Error** — processing raised an exception; the raw traceback is stored on
  the event record for inspection.
- **Dead Letter** — handler returned a dead-letter result; manual review
  required.
- **Rejected** — signature or freshness validation failed; the event will not
  be retried automatically.

Use the **State** filter and saved views to quickly isolate failures.

Reprocessing and Dead-Letter
-----------------------------

To reprocess an event in **Error** or **Dead Letter** state:

1. Open the event record.
2. Click **Reset to Received** to move it back to the ``received`` state.
3. Click **Process** to re-enqueue, or wait for the background runner.

Rejected events cannot be reset. Fix the endpoint configuration first (e.g.
correct the signature secret), then resend the request from the upstream
provider to create a fresh event.

Troubleshooting Checklist
--------------------------

- **Signature mismatch / 401**: confirm the shared secret on the endpoint
  matches the upstream provider exactly, including encoding (hex vs base64)
  and prefix stripping.
- **Events arriving as Rejected with freshness error**: the server clock may
  differ from the upstream provider; increase **Max Age** or sync NTP.
- **Events stuck in Received**: check that the ``queue_job`` worker is running
  and the job channel is not paused.
- **Duplicate events not deduplicated**: confirm the **Delivery Identity
  Policy** is set and the upstream provider sends a consistent identity header.
- **Events processed but no records created**: open the event form and inspect
  the **Matched Rule** and **Execution Log** to see which rule fired and why
  the assignment did not produce the expected record.
