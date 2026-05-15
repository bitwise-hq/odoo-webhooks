{
    "name": "Connector Webhooks - Glue Outbound",
    "version": "18.0.1.1.0",
    "category": "Tools",
    "summary": "Outbound webhook integration for connector backends.",
    "depends": [
        "bwt_connector_webhooks_core",
        "bwt_webhooks_outbound",
    ],
    "data": [
        "views/webhook_outbound_endpoint_views.xml",
    ],
    "author": "Bitwise Technologies LLC",
    "contributors": ["Youssef Egla"],
    "license": "LGPL-3",
    "website": "https://github.com/bitwise-hq/odoo-webhooks",
    "images": ["static/description/banner.png", "static/description/icon.png"],
    "installable": True,
    "auto_install": True,
}
