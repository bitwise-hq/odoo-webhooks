=================================
Connector Webhooks - Glue Inbound
=================================

Inbound side mixin for connector backends.

Provides ``bwt.connector.webhook.inbound.mixin``, an opt-in abstract
model that extends ``bwt.connector.webhook.backend.base`` with:

* the ``webhook_endpoint_id`` computed Many2one (resolved from the
  endpoint's ``connector_backend_ref``);
* the inbound callback dispatcher
  (``_handle_inbound_webhook_event``) — the framework's
  ``bwt.webhook.inbound.event._invoke_inbound_dispatch`` hook routes
  events whose endpoint carries ``connector_backend_ref`` to this
  method; backends override it to return the framework outcome dict
  (``webhook_done`` / ``webhook_dead_letter`` / ``webhook_retry`` /
  ``webhook_cancel``);
* the JSON payload decoder helper
  (``_decode_inbound_event_payload``);
* the ``action_view_inbound_endpoint`` form action.

Also extends ``bwt.webhook.inbound.endpoint`` with a
``connector_backend_ref`` reference field.

Concrete handler/endpoint records are shipped by downstream addons as
Odoo XML data and linked to a backend by an administrator (no
auto-provisioning).

Contributors
------------

* Bitwise Technologies LLC
* Youssef Egla

License
-------

LGPL-3 - `GNU Lesser General Public License v3.0 <http://www.gnu.org/licenses/lgpl-3.0-standalone.html>`_.
