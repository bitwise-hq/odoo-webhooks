"""Tests for the pure-Python services in :mod:`bwt_connector_webhooks_core.services`."""

from datetime import datetime, timezone

from odoo.tests.common import TransactionCase

from odoo.addons.bwt_connector_webhooks_core.services import (
    naming,
    payload,
    result_types,
    timestamps,
    values,
)


class TestNamingService(TransactionCase):
    """``slugify_identifier`` collapses non-alphanumerics to ``-``."""

    def test_slugify_lowercases_and_trims_separators(self):
        self.assertEqual(naming.slugify_identifier(" Hello World! "), "hello-world")

    def test_slugify_collapses_runs_of_separators(self):
        self.assertEqual(naming.slugify_identifier("a___b///c"), "a-b-c")

    def test_slugify_returns_empty_string_for_falsy_value(self):
        self.assertEqual(naming.slugify_identifier(None), "")
        self.assertEqual(naming.slugify_identifier(""), "")


class TestResultTypeFactories(TransactionCase):
    """Webhook callback result helpers build dicts with the expected status."""

    def test_done_without_note_omits_note_key(self):
        self.assertEqual(result_types.webhook_done(), {"status": "done"})

    def test_done_with_note_includes_note_key(self):
        self.assertEqual(result_types.webhook_done("ok"), {"status": "done", "note": "ok"})

    def test_dead_letter_always_includes_note(self):
        self.assertEqual(
            result_types.webhook_dead_letter("nope"),
            {"status": "dead_letter", "note": "nope"},
        )

    def test_retry_defaults_to_60_seconds(self):
        self.assertEqual(
            result_types.webhook_retry("later"),
            {"status": "retry", "note": "later", "seconds": 60},
        )

    def test_retry_accepts_custom_seconds(self):
        self.assertEqual(
            result_types.webhook_retry("later", seconds=15),
            {"status": "retry", "note": "later", "seconds": 15},
        )

    def test_cancel_with_and_without_note(self):
        self.assertEqual(result_types.webhook_cancel(), {"status": "cancel"})
        self.assertEqual(result_types.webhook_cancel("stop"), {"status": "cancel", "note": "stop"})


class TestValuesService(TransactionCase):
    """``json_serialize_value``."""

    def test_json_serialize_passes_through_strings(self):
        self.assertEqual(values.json_serialize_value("plain"), "plain")

    def test_json_serialize_serializes_non_strings_with_sorted_keys(self):
        self.assertEqual(values.json_serialize_value({"b": 2, "a": 1}), '{"a": 1, "b": 2}')


class TestTimestampService(TransactionCase):
    """``parse_iso_or_epoch_utc`` and ``normalize_odoo_datetime_utc``."""

    def test_epoch_int_is_converted_to_utc_datetime(self):
        result = timestamps.parse_iso_or_epoch_utc(1700000000)

        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(int(result.timestamp()), 1700000000)

    def test_iso_string_with_z_suffix_is_parsed(self):
        result = timestamps.parse_iso_or_epoch_utc("2024-01-01T00:00:00Z")

        self.assertEqual(result, datetime(2024, 1, 1, tzinfo=timezone.utc))

    def test_digit_string_is_treated_as_epoch(self):
        result = timestamps.parse_iso_or_epoch_utc("1700000000")

        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(int(result.timestamp()), 1700000000)

    def test_normalize_aware_datetime_converts_to_utc(self):
        from datetime import timedelta
        from unittest.mock import patch

        aware = datetime(2024, 6, 15, 14, 30, tzinfo=timezone(timedelta(hours=2)))

        # ``fields.Datetime.to_datetime`` rejects aware values; bypass it.
        with patch(
            "odoo.addons.bwt_connector_webhooks_core.services.timestamps.fields.Datetime.to_datetime",
            return_value=aware,
        ):
            result = timestamps.normalize_odoo_datetime_utc("unused")

        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result, datetime(2024, 6, 15, 12, 30, tzinfo=timezone.utc))

    def test_naive_iso_string_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Naive datetimes"):
            timestamps.parse_iso_or_epoch_utc("2024-01-01T00:00:00")

    def test_empty_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing timestamp value"):
            timestamps.parse_iso_or_epoch_utc(None)
        with self.assertRaisesRegex(ValueError, "Empty timestamp value"):
            timestamps.parse_iso_or_epoch_utc("   ")

    def test_unsupported_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported timestamp type"):
            timestamps.parse_iso_or_epoch_utc([1, 2, 3])


class TestPayloadService(TransactionCase):
    """``parse_json_object`` decodes raw payloads leniently."""

    def test_none_returns_empty_dict(self):
        self.assertEqual(payload.parse_json_object(None), {})

    def test_empty_string_returns_empty_dict(self):
        self.assertEqual(payload.parse_json_object(""), {})

    def test_dict_returned_as_is(self):
        d = {"k": 1}
        self.assertIs(payload.parse_json_object(d), d)

    def test_valid_json_string_decoded(self):
        self.assertEqual(payload.parse_json_object('{"a": 1}'), {"a": 1})

    def test_invalid_json_string_returns_empty_dict(self):
        self.assertEqual(payload.parse_json_object("not json"), {})

    def test_json_non_dict_returns_empty_dict(self):
        self.assertEqual(payload.parse_json_object("[1,2,3]"), {})

    def test_bytes_decoded_and_parsed(self):
        self.assertEqual(payload.parse_json_object(b'{"b": 2}'), {"b": 2})

    def test_bytes_invalid_utf8_returns_empty_dict(self):
        self.assertEqual(payload.parse_json_object(b"\xff\xfe"), {})

    def test_non_str_bytes_returns_empty_dict(self):
        self.assertEqual(payload.parse_json_object(42), {})

    def test_normalize_odoo_datetime_returns_utc_aware(self):
        result = timestamps.normalize_odoo_datetime_utc("2024-06-15 12:30:00")

        self.assertEqual(result.tzinfo, timezone.utc)

    def test_normalize_odoo_datetime_rejects_missing_value(self):
        with self.assertRaisesRegex(ValueError, "Missing Odoo datetime"):
            timestamps.normalize_odoo_datetime_utc(False)
