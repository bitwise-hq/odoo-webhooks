"""Pure-Python helpers used by the bwt_connector_webhooks_* addons.

These modules deliberately avoid importing the Odoo ORM, with one narrow
exception: :mod:`.timestamps` uses :func:`odoo.fields.Datetime.to_datetime`
to interpret Odoo Datetime field values.
"""

from . import naming
from . import result_types
from . import timestamps
from . import values
