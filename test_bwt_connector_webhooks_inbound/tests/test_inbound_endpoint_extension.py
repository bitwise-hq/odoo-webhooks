"""Tests for the inbound endpoint reference and company-match constraint."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class _BackendInboundTestCase(TransactionCase):
    BACKEND_MODEL = "bwt.test.connector.webhook.backend.inbound"

    def setUp(self):
        super().setUp()
        self.backend = self.env[self.BACKEND_MODEL].create({"name": "Acme", "code": "acme"})
        self.handler = self.env["bwt.webhook.handler"].create(
            {
                "name": "Test Inbound",
                "code": f"test-inbound-{self.backend.id}",
                "direction": "inbound",
                "execution_mode": "model_driven",
            }
        )
        self.endpoint = self.env["bwt.webhook.inbound.endpoint"].create(
            {
                "name": "Test Inbound Endpoint",
                "path": f"acme-{self.backend.id}",
                "handler_id": self.handler.id,
                "delivery_identity_policy": "body_sha256",
                "connector_backend_ref": f"{self.BACKEND_MODEL},{self.backend.id}",
            }
        )


class TestInboundEndpointReference(_BackendInboundTestCase):
    """Inbound endpoints carry a reference to their owning backend."""

    def test_reference_points_to_backend(self):
        self.assertEqual(self.endpoint.connector_backend_ref, self.backend)

    def test_unique_constraint_prevents_two_endpoints_per_backend(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(Exception):
            self.env["bwt.webhook.inbound.endpoint"].create(
                {
                    "name": "second",
                    "path": f"second-{self.backend.id}",
                    "handler_id": self.handler.id,
                    "delivery_identity_policy": "body_sha256",
                    "connector_backend_ref": f"{self.backend._name},{self.backend.id}",
                }
            )


class TestInboundEndpointCompanyMatch(_BackendInboundTestCase):
    """``_check_connector_backend_company`` enforces matching companies."""

    def test_endpoint_company_matches_backend_company_passes(self):
        self.assertEqual(self.endpoint.company_id, self.backend.company_id)

    def test_mismatched_company_is_rejected(self):
        other_company = self.env["res.company"].create({"name": "Other"})

        with self.assertRaisesRegex(ValidationError, "company must match"):
            self.endpoint.write({"company_id": other_company.id})

    def test_endpoint_without_backend_ref_passes_constraint(self):
        # The constraint loops over endpoints and uses ``continue`` when
        # ``connector_backend_ref`` is unset.
        endpoint = self.endpoint.copy(
            {
                "name": "Standalone",
                "path": f"standalone-{self.backend.id}",
                "connector_backend_ref": False,
            }
        )

        endpoint._check_connector_backend_company()
