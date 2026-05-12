from . import services  # noqa: F401  (loads pure-Python helpers)
from . import models


def pre_init_hook(cr):
    """Ensure the OCA ``queue_job`` addon is installed before this addon loads.

    ``queue_job`` is a required runtime dependency but is intentionally omitted
    from ``depends`` because it is not yet published on the Odoo Apps Store for
    all supported series.  For early-adopter deployments, place the ahead-of-store
    fork on the addons path before installing this addon:
    https://github.com/bitwise-hq/odoo-oca-queue
    """
    cr.execute("SELECT state FROM ir_module_module WHERE name = 'queue_job'")
    row = cr.fetchone()
    if not row or row[0] != "installed":  # pragma: no cover
        raise ValueError("The 'queue_job' addon (OCA/queue) must be installed before installing bwt_webhooks_core.\nRun: odoo -i queue_job  (or install it from Apps after placing the addon on your addons path).\nEarly-adopter fork: https://github.com/bitwise-hq/odoo-oca-queue")
