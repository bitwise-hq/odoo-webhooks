Operator Guide: Operations
==========================

Audience
--------

This guide is for operators and administrators reviewing traffic, retrying
work, creating replays, and understanding the audit trail.

Inbound events
--------------

Inbound events store the accepted or rejected request evidence for an inbound
endpoint.

Important states are:

* ``received``
* ``processing``
* ``done``
* ``error``
* ``dead_letter``
* ``rejected``

Use the event form to review:

* resolved values and semantic fields
* request headers and body snapshots
* rejection category and error text
* matched inbound rule and execution log rows

Use ``Queue Processing`` to send a received or failed event back to the queue.
Use ``Reset to Received`` only for ``error`` or ``dead_letter`` events.
Rejected events are kept as audit evidence and are not the same as retriable
failures.

Outbound deliveries
-------------------

Outbound deliveries are the durable rows that queue and send outbound HTTP
requests.

Important states are:

* ``draft``
* ``queued``
* ``processing``
* ``done``
* ``error``
* ``dead_letter``
* ``canceled``

Use the delivery form to review:

* request headers and payload snapshots
* response status, headers, and body
* matched outbound rule
* context lines
* attempt history
* replay lineage

Replay vs reset
---------------

``Reset to Draft``
  Reuses the same delivery row after a failure or cancellation.

``Create Replay Delivery``
  Creates a new draft delivery linked to the original one.

Choose replay when you need a new audited resend record. Choose reset only when
the existing delivery row should be reused.

Queue jobs and attempts
-----------------------

Queue jobs show background execution intent. Attempt rows show actual HTTP send
attempts and their results.

When debugging outbound issues, check these in order:

1. delivery state and processing note
2. matched outbound rule
3. latest attempt record
4. response status and body
5. queue job state if the delivery never left ``queued``

Runtime snapshots
-----------------

The request and response JSON fields on inbound events and outbound deliveries
are runtime evidence. They exist so operators can see what was received or sent.
They are not the place where configuration should be authored.

Common troubleshooting checks
-----------------------------

Inbound duplicate rejected unexpectedly
  Re-check the endpoint identity policy and semantic bindings.

Inbound event stored but no business action ran
  Review the handler, execution mode, and matched rule execution log.

Outbound delivery never sent
  Check the endpoint state, delivery state, execution user, and queue jobs.

Outbound delivery dead-lettered
  Review the response status and the last attempt for client-side HTTP errors.

Partner-scoped records are missing from a user view
  Ask an administrator to confirm the user's allowed partner list.

See also
--------

* `Operator inbound setup <operator_inbound_setup.rst>`_
* `Operator outbound setup <operator_outbound_setup.rst>`_
* `Developer testing <developer_testing.rst>`_
