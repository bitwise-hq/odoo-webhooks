"""Pure-Python service layer for the webhooks addon.

Modules in this package must not import :mod:`odoo` (the model layer
imports from here, not the other way around). They contain value
objects, parsers, formatters, and orchestrators that the ORM models
delegate to.
"""

from . import conditions
from . import constants
from . import identity
from . import payload
from . import serialization
from . import signature
from . import transport
from . import value_extraction
from . import value_objects
