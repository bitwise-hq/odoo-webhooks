==============================
Connector Webhooks - Glue Core
==============================

Shared base for connector backends that own webhook endpoints.

This addon ships ``bwt.connector.webhook.backend.base``, a private
abstract model that is **not** inherited directly by concrete backends.
Backends opt in by inheriting one (or both) of the side mixins shipped
by ``bwt_connector_webhooks_inbound`` and ``bwt_connector_webhooks_outbound``.

The base provides:

* the integration contract (canonical webhook fields, marker for the
  reference selection used by endpoint extensions);
* scoping, normalization and validation primitives for the backend
  ``code`` field shared with both inbound and outbound mixins.

Concrete handler/endpoint records are shipped by downstream addons as
Odoo XML data records and linked to a backend by an administrator (no
auto-provisioning).

Contributors
------------

* Bitwise Technologies LLC
* Youssef Egla

License
-------

LGPL-3 - `GNU Lesser General Public License v3.0 <http://www.gnu.org/licenses/lgpl-3.0-standalone.html>`_.
