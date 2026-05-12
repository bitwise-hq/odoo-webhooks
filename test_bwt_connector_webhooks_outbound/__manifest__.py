{
    "name": "Tests: Connector Webhooks Outbound",
    "version": "17.0.1.0.0",
    "category": "Hidden",
    "summary": "Tests for the bwt_connector_webhooks_outbound addon.",
    "depends": [
        "bwt_connector_webhooks_outbound",
        "bwt_connector_webhooks_inbound",
        "test_bwt_connector_webhooks_core",
        "test_bwt_webhooks_outbound",
    ],
    "data": [
        "security/ir.model.access.csv",
    ],
    "author": "Bitwise Technologies LLC",
    "contributors": ["Youssef Egla"],
    "license": "LGPL-3",
    "installable": True,
    "auto_install": False,
}
