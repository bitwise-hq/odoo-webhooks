"""Webhook callback result factories.

The connector_webhooks side mixins expect callback handlers (inbound and
outbound) to return a dict shaped as ``{"status": ..., "note": ..., ...}``.
"""


def webhook_done(note=None):
    return {"status": "done", "note": note} if note else {"status": "done"}


def webhook_dead_letter(note):
    return {"status": "dead_letter", "note": note}


def webhook_retry(note, seconds=60):
    return {"status": "retry", "note": note, "seconds": seconds}


def webhook_cancel(note=None):
    return {"status": "cancel", "note": note} if note else {"status": "cancel"}
