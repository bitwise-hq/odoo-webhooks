{
    "name": "Tests: Connector Webhooks Inbound",
    "version": "16.0.1.0.0",
    "category": "Hidden",
    "summary": "Tests for the bwt_connector_webhooks_inbound addon.",
    "depends": [
        "bwt_connector_webhooks_inbound",
        "test_bwt_connector_webhooks_core",
        "test_bwt_webhooks_inbound",
    ],
    "data": [
        "security/ir.model.access.csv",
    ],
    "author": "Bitwise Technologies LLC",
    "contributors": ["Youssef Egla"],
    "license": "OPL-1",
    "installable": True,
    "auto_install": False,
}
