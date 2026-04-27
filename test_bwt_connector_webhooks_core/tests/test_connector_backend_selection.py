"""Tests for ``connector.backend._selection_connector_webhook_backend_models``."""

from odoo.tests.common import TransactionCase


class TestConnectorBackendSelection(TransactionCase):
    """The selection enumerates concrete models flagged with the marker."""

    def test_selection_includes_the_in_test_minimal_backend_model(self):
        selection = self.env["connector.backend"]._selection_connector_webhook_backend_models()

        models = [model_name for model_name, _label in selection]

        self.assertIn("bwt.test.connector.webhook.backend.minimal", models)

    def test_selection_excludes_the_abstract_base_model(self):
        selection = self.env["connector.backend"]._selection_connector_webhook_backend_models()

        models = [model_name for model_name, _label in selection]

        self.assertNotIn("bwt.connector.webhook.backend.base", models)
        self.assertNotIn("bwt.connector.webhook.inbound.mixin", models)
        self.assertNotIn("bwt.connector.webhook.outbound.mixin", models)

    def test_selection_returns_label_for_each_model(self):
        selection = self.env["connector.backend"]._selection_connector_webhook_backend_models()

        for _model_name, label in selection:
            self.assertTrue(label)
