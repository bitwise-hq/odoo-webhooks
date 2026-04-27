"""Tests for the outbound endpoint reference and company-match constraint."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class _BackendOutboundTestCase(TransactionCase):
    BACKEND_MODEL = "bwt.test.connector.webhook.backend.outbound"

    def setUp(self):
        super().setUp()
        self.backend = self.env[self.BACKEND_MODEL].create({"name": "Acme", "code": "acme"})
        self.endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Primary",
                "code": f"primary-{self.backend.id}",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/primary",
                "connector_backend_ref": f"{self.BACKEND_MODEL},{self.backend.id}",
            }
        )


class TestOutboundEndpointReference(_BackendOutboundTestCase):
    """Outbound endpoints carry a reference to their owning backend."""

    def test_reference_points_to_backend(self):
        self.assertEqual(self.endpoint.connector_backend_ref, self.backend)


class TestOutboundEndpointCompanyMatch(_BackendOutboundTestCase):
    """``_check_connector_backend_company`` enforces matching companies."""

    def test_mismatched_company_is_rejected(self):
        other_company = self.env["res.company"].create({"name": "Other"})

        with self.assertRaisesRegex(ValidationError, "company must match"):
            self.endpoint.write({"company_id": other_company.id})

    def test_endpoint_without_backend_ref_passes_constraint(self):
        endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Standalone",
                "code": "standalone-out",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/x",
                "timeout_seconds": 5,
            }
        )

        endpoint._check_connector_backend_company()
