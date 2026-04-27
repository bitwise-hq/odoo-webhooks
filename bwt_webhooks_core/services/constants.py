"""Module-level constants shared across services and ORM models.

Selection lists are duplicated here as plain Python tuples so service
code can validate and label values without importing the ORM models.
"""

# Inbound endpoint selections ------------------------------------------------

SIGNATURE_MODE_SELECTION = (
    ("none", "None"),
    ("hmac", "Shared Secret HMAC"),
)
SIGNATURE_DIGEST_SELECTION = (
    ("sha1", "SHA1"),
    ("sha256", "SHA256"),
    ("sha512", "SHA512"),
)
SIGNATURE_ENCODING_SELECTION = (
    ("hex", "Hex"),
    ("base64", "Base64"),
)
TIMESTAMP_FORMAT_SELECTION = (
    ("unix", "Unix Seconds"),
    ("unix_ms", "Unix Milliseconds"),
    ("iso8601", "ISO 8601"),
)
PAYLOAD_CONTRACT_SELECTION = (
    ("json_object", "JSON Object"),
    ("json_value", "Any JSON Value"),
)
DELIVERY_IDENTITY_POLICY_SELECTION = (
    ("delivery_id", "Delivery Identity"),
    ("idempotency_key", "Explicit Idempotency Key"),
    ("body_sha256", "Raw Body SHA256"),
)
REPLAY_IDENTITY_POLICY_SELECTION = (
    ("none", "None"),
    ("event_id", "Business Event Identity"),
    ("idempotency_key", "Explicit Idempotency Key"),
)
ENDPOINT_STATE_SELECTION = (
    ("draft", "Draft"),
    ("active", "Active"),
    ("archived", "Archived"),
)

DELIVERY_POLICY_LABELS = dict(DELIVERY_IDENTITY_POLICY_SELECTION)
REPLAY_POLICY_LABELS = dict(REPLAY_IDENTITY_POLICY_SELECTION)


# Outbound delivery handler outcomes ----------------------------------------

OUTCOME_SEND = "send"
OUTCOME_CANCEL = "cancel"
OUTCOME_DEAD_LETTER = "dead_letter"
OUTCOME_RETRY = "retry"

TERMINAL_OUTCOME_STATE = {
    OUTCOME_CANCEL: "canceled",
    OUTCOME_DEAD_LETTER: "dead_letter",
}


# Outbound request body modes -----------------------------------------------

OUTBOUND_REQUEST_BODY_MODE_SELECTION = (
    ("json", "JSON"),
    ("form_urlencoded", "Form URL Encoded"),
    ("multipart", "Multipart Form Data"),
)

VALID_OUTBOUND_BODY_MODES = frozenset(mode for mode, _label in OUTBOUND_REQUEST_BODY_MODE_SELECTION)


# Generic ----------------------------------------------------------------

BLANK_VALUES = (False, None, "")
