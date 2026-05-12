{
    "name": "Webhooks Connector - Core Orchestration",
    "version": "16.0.1.0.0",
    "category": "Tools",
    "summary": "Shared base for connector backends that own webhook endpoints.",
    "depends": [
        "bwt_webhooks_core",
        "connector",
    ],
    "pre_init_hook": "pre_init_hook",
    "author": "Bitwise Technologies LLC",
    "contributors": ["Youssef Egla"],
    "license": "LGPL-3",
    "images": ["static/description/banner.png", "static/description/icon.png"],
    "installable": True,
    "auto_install": True,
}
