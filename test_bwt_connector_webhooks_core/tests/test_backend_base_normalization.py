"""Tests for code normalization and validation on the base abstract model."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class _BackendBaseTestCase(TransactionCase):
    BACKEND_MODEL = "bwt.test.connector.webhook.backend.minimal"

    def setUp(self):
        super().setUp()
        self.backend_model = self.env[self.BACKEND_MODEL]

    def _create(self, **overrides):
        vals = {
            "name": "Acme",
            "code": "acme",
            **overrides,
        }
        return self.backend_model.create(vals)


class TestBackendBaseCodeNormalization(_BackendBaseTestCase):
    """``_prepare_webhook_backend_vals`` slugifies the code on create/write."""

    def test_create_slugifies_provided_code(self):
        backend = self._create(code=" Acme Co! ")

        self.assertEqual(backend.code, "acme-co")

    def test_create_defaults_code_from_name_when_missing(self):
        backend = self.backend_model.create({"name": "My Backend"})

        self.assertEqual(backend.code, "my-backend")

    def test_write_renormalizes_code(self):
        backend = self._create()

        backend.write({"code": "New_Code"})

        self.assertEqual(backend.code, "new-code")

    def test_validate_rejects_blank_code(self):
        backend = self._create()

        with self.assertRaisesRegex(ValidationError, "technical code"):
            backend.write({"code": False})


class TestBackendBaseDirectCodeValidation(_BackendBaseTestCase):
    """``_validate_webhook_backend_code`` rejects an unslugified code."""

    def test_non_slugified_code_is_rejected(self):
        backend = self._create()
        # Bypass ORM-side ``_prepare_webhook_backend_vals`` slugification by
        # writing through the database; the ``@api.constrains`` then fires
        # ``_validate_webhook_backend_code`` and raises.
        self.env.cr.execute(
            "UPDATE %s SET code = %%s WHERE id = %%s" % self.backend_model._table,
            ("Bad_Code", backend.id),
        )
        backend.invalidate_recordset(["code"])
        with self.assertRaisesRegex(ValidationError, "letters, digits"):
            backend._validate_webhook_backend_code()


class TestBackendBaseScopingPrimitives(_BackendBaseTestCase):
    """Scoping primitive helpers on the abstract backend base."""

    NO_COMPANY_MODEL = "bwt.test.connector.webhook.backend.minimal.no.company"

    def test_scope_company_id_returns_int_when_company_is_set(self):
        backend = self._create()

        result = backend._get_backend_scope_company_id()

        self.assertEqual(result, self.env.company.id)

    def test_scope_company_id_returns_false_when_no_company(self):
        # The no-company model has no company_id field (or it is unset).
        backend = self.env[self.NO_COMPANY_MODEL].create({"name": "NoComp", "code": "no-comp"})

        result = backend._get_backend_scope_company_id()

        self.assertFalse(result)

    def test_technical_prefix_contains_id(self):
        backend = self._create()

        prefix = backend._get_technical_prefix()

        self.assertIn(str(backend.id), prefix)

    def test_build_scoped_technical_name_without_suffix_returns_prefix(self):
        backend = self._create()

        result = backend._build_backend_scoped_technical_name()

        self.assertEqual(result, backend._get_technical_prefix())

    def test_build_scoped_technical_name_with_suffix_appends_slug(self):
        backend = self._create()

        result = backend._build_backend_scoped_technical_name(suffix="My Handler")

        self.assertTrue(result.endswith("-my-handler"))

    def test_build_scoped_display_name_without_suffix_returns_display_name(self):
        backend = self._create()

        result = backend._build_backend_scoped_display_name()

        self.assertEqual(result, backend.display_name)

    def test_build_scoped_display_name_with_suffix_appends_text(self):
        backend = self._create()

        result = backend._build_backend_scoped_display_name(suffix="Inbound")

        self.assertEqual(result, f"{backend.display_name} Inbound")

    def test_prepare_vals_write_without_code_is_passthrough(self):
        # write() with no code field → elif for_create branch evaluates False
        # and ``return prepared`` is reached without modifying any field.
        backend = self._create()

        prepared = backend._prepare_webhook_backend_vals({"name": "New Name"})

        self.assertEqual(prepared, {"name": "New Name"})
