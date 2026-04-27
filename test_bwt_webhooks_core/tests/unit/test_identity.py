"""Unit tests for :mod:`bwt_webhooks_core.services.identity`.

Test suites in this module:

* :class:`TestResolveDeliveryIdentity` — selects the delivery fingerprint
  used to dedupe inbound events.
* :class:`TestResolveReplayIdentity` — selects the optional replay key
  used to detect provider-side retries.
"""

from .common import WebhookServiceTestCase

from odoo.addons.bwt_webhooks_core.services.identity import (
    IdentityNotResolvable,
    resolve_delivery_identity,
    resolve_replay_identity,
)


class TestResolveDeliveryIdentity(WebhookServiceTestCase):
    """``resolve_delivery_identity`` picks the delivery fingerprint by policy."""

    def test_default_policy_uses_delivery_id(self):
        value, policy = resolve_delivery_identity("hash", {"delivery_id": "evt_1"}, policy=None)
        self.assertEqual((value, policy), ("evt_1", "delivery_id"))

    def test_body_sha256_bypasses_metadata(self):
        value, policy = resolve_delivery_identity("hash", {"delivery_id": "x"}, policy="body_sha256")
        self.assertEqual((value, policy), ("hash", "body_sha256"))

    def test_raises_with_policy_attribute_when_missing(self):
        with self.assertRaises(IdentityNotResolvable) as ctx:
            resolve_delivery_identity("h", {}, policy="delivery_id")
        self.assertEqual(ctx.exception.policy, "delivery_id")


class TestResolveReplayIdentity(WebhookServiceTestCase):
    """``resolve_replay_identity`` extracts the optional replay key by policy."""

    def test_none_policy_returns_pair_of_false(self):
        self.assertEqual(resolve_replay_identity({"x": "y"}, policy=None), (False, False))
        self.assertEqual(resolve_replay_identity({"x": "y"}, policy="none"), (False, False))

    def test_returns_value_when_policy_set(self):
        value, policy = resolve_replay_identity({"replay_id": "r_1"}, policy="replay_id")
        self.assertEqual((value, policy), ("r_1", "replay_id"))

    def test_raises_when_policy_value_missing(self):
        with self.assertRaises(IdentityNotResolvable) as ctx:
            resolve_replay_identity({}, policy="replay_id")
        self.assertEqual(ctx.exception.policy, "replay_id")
