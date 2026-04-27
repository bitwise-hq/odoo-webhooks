"""Pure-Python unit tests for ``webhooks.services``.

These tests do not touch the ORM and run as plain :class:`unittest.TestCase`
subclasses. They exist alongside the integration tests under
:mod:`webhooks.tests` so the existing Odoo test runner discovers them
through the package ``__init__``.
"""

from . import test_value_extraction
from . import test_serialization
from . import test_value_objects
from . import test_signature
from . import test_identity
from . import test_transport
from . import test_conditions
from . import test_payload
