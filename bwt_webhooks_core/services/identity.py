"""Pure identity-resolution helpers for inbound webhook deduplication.

Both the delivery- and replay-identity policies follow the same
shape: pick a value out of a metadata mapping (or fall back to a body
hash) and report which policy provided it. The model delegates here
so the policies can be unit-tested without an ORM.
"""

from typing import Optional, Tuple


class IdentityNotResolvable(Exception):
    """Raised when the configured policy did not produce a value.

    Carries the symbolic policy name so the caller can localize the
    error message via the :data:`webhooks.services.constants` label
    maps.
    """

    def __init__(self, policy: str):
        super().__init__(policy)
        self.policy = policy


def resolve_delivery_identity(body_sha256: str, metadata: dict, *, policy: Optional[str]) -> Tuple[str, str]:
    """Return ``(value, policy)`` for the delivery identity.

    ``policy`` defaults to ``"delivery_id"`` when blank. The
    ``body_sha256`` policy bypasses ``metadata`` entirely.
    """
    chosen = policy or "delivery_id"
    if chosen == "body_sha256":
        return body_sha256, "body_sha256"
    candidate = metadata.get(chosen)
    if candidate:
        return candidate, chosen
    raise IdentityNotResolvable(chosen)


def resolve_replay_identity(metadata: dict, *, policy: Optional[str]) -> Tuple:
    """Return ``(value, policy)`` for the replay identity, or ``(False, False)``.

    ``policy`` defaults to ``"none"`` (no replay tracking).
    """
    chosen = policy or "none"
    if chosen == "none":
        return False, False
    candidate = metadata.get(chosen)
    if candidate:
        return candidate, chosen
    raise IdentityNotResolvable(chosen)
