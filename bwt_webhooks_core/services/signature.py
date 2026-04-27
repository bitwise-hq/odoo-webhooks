"""Pure cryptographic and timestamp helpers for inbound HMAC verification.

The :class:`bwt.webhook.inbound.endpoint` model owns the ORM-bound
configuration (recordsets of signature parts, secret fields). This
module exposes the algorithmic primitives the model delegates to:

* :func:`compute_expected_signature` — HMAC + digest encoding.
* :func:`strip_signature_prefix` — drop the documented prefix from
  incoming candidates before comparing.
* :func:`verify_signature_against_secrets` — constant-time match
  across primary/secondary secrets.
* :func:`parse_signature_timestamp` — UTC datetime parser for the
  three documented timestamp formats.
* :func:`validate_signature_freshness` — age + future-skew check.
"""

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Iterable, Optional


def compute_expected_signature(secret: str, message: str, *, digest_algorithm: str, encoding: str) -> str:
    """Return the expected HMAC signature for ``message`` under ``secret``.

    ``digest_algorithm`` is one of the names supported by ``hashlib``
    (``"sha1"``, ``"sha256"``, ``"sha512"``); ``encoding`` is either
    ``"hex"`` or ``"base64"``.
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        getattr(hashlib, digest_algorithm),
    ).digest()
    if encoding == "hex":
        return digest.hex()
    return base64.b64encode(digest).decode("utf-8")


def strip_signature_prefix(candidates: Iterable, prefix: Optional[str]) -> list:
    """Drop ``prefix`` from each value in ``candidates`` (when present).

    A falsy ``prefix`` is a no-op; values are still coerced to ``str``.
    """
    cleaned = []
    pfx = prefix or ""
    for value in candidates:
        text = str(value)
        if pfx and text.startswith(pfx):
            text = text[len(pfx) :]
        cleaned.append(text)
    return cleaned


def verify_signature_against_secrets(
    message: str,
    candidates: Iterable[str],
    secrets: Iterable[str],
    *,
    digest_algorithm: str,
    encoding: str,
) -> bool:
    """Return ``True`` when any ``candidate`` matches the expected HMAC.

    Performs a constant-time comparison via :func:`hmac.compare_digest`
    against every (secret, candidate) pair.
    """
    candidate_list = list(candidates)
    for secret in secrets:
        expected = compute_expected_signature(secret, message, digest_algorithm=digest_algorithm, encoding=encoding)
        for candidate in candidate_list:
            if hmac.compare_digest(candidate, expected):
                return True
    return False


def parse_signature_timestamp(raw_value, *, timestamp_format: str) -> Optional[datetime]:
    """Parse a signature timestamp into a UTC :class:`datetime`.

    Returns ``False`` for blank inputs so callers can keep the existing
    truthiness-based control flow.
    """
    if raw_value in (False, None, ""):
        return False
    if timestamp_format == "unix":
        return datetime.fromtimestamp(int(raw_value), timezone.utc)
    if timestamp_format == "unix_ms":
        return datetime.fromtimestamp(int(raw_value) / 1000.0, timezone.utc)
    parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_signature_freshness(
    received_at: datetime,
    *,
    max_age_seconds: int,
    max_future_skew_seconds: int,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Compare ``received_at`` to ``now`` against age and skew limits.

    Returns ``None`` when fresh, or a short reason code (``"too_old"``
    or ``"too_future"``) the caller can map to a localized error
    message. Both limits are skipped when ``<= 0``.
    """
    if max_age_seconds <= 0 and max_future_skew_seconds <= 0:
        return None
    current = now or datetime.now(timezone.utc)
    age_seconds = (current - received_at).total_seconds()
    if max_age_seconds > 0 and age_seconds > max_age_seconds:
        return "too_old"
    if max_future_skew_seconds > 0 and age_seconds < -max_future_skew_seconds:
        return "too_future"
    return None
