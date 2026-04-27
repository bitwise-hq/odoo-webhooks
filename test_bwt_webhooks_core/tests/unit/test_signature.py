"""Unit tests for :mod:`bwt_webhooks_core.services.signature`.

Test suites in this module:

* :class:`TestComputeExpectedSignature` — HMAC digest computation
  across algorithms and encodings.
* :class:`TestStripSignaturePrefix` — normalization of provider-prefixed
  signature header values.
* :class:`TestVerifySignatureAgainstSecrets` — constant-time signature
  comparison against multiple rotated secrets.
* :class:`TestParseSignatureTimestamp` — parsing of timestamp formats
  carried alongside webhook signatures.
* :class:`TestValidateSignatureFreshness` — anti-replay window check
  for inbound signed deliveries.
"""

import hmac
import hashlib
from .common import WebhookServiceTestCase
from datetime import datetime, timedelta, timezone

from odoo.addons.bwt_webhooks_core.services.signature import (
    compute_expected_signature,
    parse_signature_timestamp,
    strip_signature_prefix,
    validate_signature_freshness,
    verify_signature_against_secrets,
)


def _expected(secret, message, *, algo="sha256"):
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        getattr(hashlib, algo),
    ).hexdigest()


class TestComputeExpectedSignature(WebhookServiceTestCase):
    """``compute_expected_signature`` produces HMAC digests in any encoding."""

    def test_hex_encoding_matches_hmac(self):
        sig = compute_expected_signature("s", "msg", digest_algorithm="sha256", encoding="hex")
        self.assertEqual(sig, _expected("s", "msg"))

    def test_base64_encoding_decodes_to_same_digest(self):
        import base64

        sig = compute_expected_signature("s", "msg", digest_algorithm="sha256", encoding="base64")
        decoded = base64.b64decode(sig)
        raw = hmac.new(b"s", b"msg", hashlib.sha256).digest()
        self.assertEqual(decoded, raw)

    def test_supports_other_algorithms(self):
        sig = compute_expected_signature("s", "msg", digest_algorithm="sha512", encoding="hex")
        self.assertEqual(sig, _expected("s", "msg", algo="sha512"))


class TestStripSignaturePrefix(WebhookServiceTestCase):
    """``strip_signature_prefix`` removes a provider tag from header values."""

    def test_strips_when_prefix_present(self):
        result = strip_signature_prefix(["sha256=abc", "raw"], "sha256=")
        self.assertEqual(result, ["abc", "raw"])

    def test_no_op_for_blank_prefix(self):
        self.assertEqual(strip_signature_prefix(["abc"], None), ["abc"])
        self.assertEqual(strip_signature_prefix(["abc"], ""), ["abc"])

    def test_coerces_values_to_strings(self):
        self.assertEqual(strip_signature_prefix([7], None), ["7"])


class TestVerifySignatureAgainstSecrets(WebhookServiceTestCase):
    """``verify_signature_against_secrets`` matches any provided secret."""

    def test_returns_true_when_any_secret_matches(self):
        message = "payload"
        good = _expected("primary", message)
        self.assertTrue(
            verify_signature_against_secrets(
                message,
                ["unrelated", good],
                ["primary", "secondary"],
                digest_algorithm="sha256",
                encoding="hex",
            )
        )

    def test_returns_true_for_secondary_secret(self):
        good = _expected("secondary", "msg")
        self.assertTrue(
            verify_signature_against_secrets(
                "msg",
                [good],
                ["primary", "secondary"],
                digest_algorithm="sha256",
                encoding="hex",
            )
        )

    def test_returns_false_when_no_match(self):
        self.assertFalse(
            verify_signature_against_secrets(
                "msg",
                ["definitely-wrong"],
                ["primary"],
                digest_algorithm="sha256",
                encoding="hex",
            )
        )


class TestParseSignatureTimestamp(WebhookServiceTestCase):
    """``parse_signature_timestamp`` decodes unix and ISO8601 timestamps."""

    def test_blank_returns_false(self):
        self.assertFalse(parse_signature_timestamp(False, timestamp_format="unix"))
        self.assertFalse(parse_signature_timestamp("", timestamp_format="unix"))

    def test_unix_seconds(self):
        ts = parse_signature_timestamp(1_700_000_000, timestamp_format="unix")
        self.assertEqual(ts, datetime.fromtimestamp(1_700_000_000, timezone.utc))

    def test_unix_milliseconds(self):
        ts = parse_signature_timestamp(1_700_000_000_000, timestamp_format="unix_ms")
        self.assertEqual(ts, datetime.fromtimestamp(1_700_000_000, timezone.utc))

    def test_iso8601_z_suffix(self):
        ts = parse_signature_timestamp("2024-01-02T03:04:05Z", timestamp_format="iso8601")
        self.assertEqual(ts, datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc))

    def test_iso8601_naive_assumed_utc(self):
        ts = parse_signature_timestamp("2024-01-02T03:04:05", timestamp_format="iso8601")
        self.assertEqual(ts, datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc))


class TestValidateSignatureFreshness(WebhookServiceTestCase):
    """``validate_signature_freshness`` enforces age and skew limits."""

    def setUp(self):
        super().setUp()
        self.now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_no_check_when_both_limits_disabled(self):
        verdict = validate_signature_freshness(self.now, max_age_seconds=0, max_future_skew_seconds=0, now=self.now)
        self.assertIsNone(verdict)

    def test_too_old(self):
        received = self.now - timedelta(seconds=120)
        verdict = validate_signature_freshness(
            received,
            max_age_seconds=60,
            max_future_skew_seconds=10,
            now=self.now,
        )
        self.assertEqual(verdict, "too_old")

    def test_too_future(self):
        received = self.now + timedelta(seconds=120)
        verdict = validate_signature_freshness(
            received,
            max_age_seconds=60,
            max_future_skew_seconds=10,
            now=self.now,
        )
        self.assertEqual(verdict, "too_future")

    def test_in_window(self):
        verdict = validate_signature_freshness(
            self.now,
            max_age_seconds=60,
            max_future_skew_seconds=10,
            now=self.now,
        )
        self.assertIsNone(verdict)
