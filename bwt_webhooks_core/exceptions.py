from odoo.exceptions import ValidationError


class WebhookValidationError(ValidationError):
    rejection_category = "validation"
    http_status_code = 400


class WebhookPayloadValidationError(WebhookValidationError):
    rejection_category = "payload"


class WebhookSignatureValidationError(WebhookValidationError):
    rejection_category = "signature"
    http_status_code = 403


class WebhookFreshnessValidationError(WebhookSignatureValidationError):
    rejection_category = "freshness"


class WebhookProcessingConfigurationError(WebhookValidationError):
    rejection_category = "configuration"
