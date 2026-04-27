from . import models
from . import services


def pre_init_hook(env):
    """Ensure the OCA ``connector`` addon is installed before this addon loads.

    ``connector`` is a required runtime dependency but is intentionally omitted
    from ``depends`` because it is not yet published on the Odoo Apps Store for
    all supported series.  For early-adopter deployments, place the ahead-of-store
    fork on the addons path before installing this addon:
    https://github.com/bitwise-hq/odoo-oca-connector
    """
    connector = env["ir.module.module"].search([("name", "=", "connector")])
    if not connector or connector.state != "installed":  # pragma: no cover
        raise ValueError("The 'connector' addon (OCA/connector) must be installed before installing bwt_connector_webhooks_core.\nRun: odoo -i connector  (or install it from Apps after placing the addon on your addons path).\nEarly-adopter fork: https://github.com/bitwise-hq/odoo-oca-connector")
