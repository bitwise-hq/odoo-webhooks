{
    "name": "Webhooks Connector - Inbound Gateway",
    "version": "16.0.1.0.0",
    "category": "Tools",
    "summary": "Inbound webhook integration for connector backends.",
    "depends": [
        "bwt_connector_webhooks_core",
        "bwt_webhooks_inbound",
    ],
    "data": [
        "views/webhook_inbound_endpoint_views.xml",
    ],
    "author": "Bitwise Technologies LLC",
    "contributors": ["Youssef Egla"],
    "license": "LGPL-3",
    "website": "https://github.com/bitwise-hq/odoo-webhooks",
    "images": ["static/description/banner.png", "static/description/icon.png"],
    "installable": True,
    "auto_install": True,
}
