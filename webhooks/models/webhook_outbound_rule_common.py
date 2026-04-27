OUTBOUND_RULE_STATUS_SELECTION = [
    ('send', 'Send'),
    ('cancel', 'Cancel'),
    ('dead_letter', 'Dead Letter'),
    ('retry', 'Retry'),
]

OUTBOUND_RULE_SOURCE_SELECTION = [
    ('literal', 'Literal'),
    ('delivery_field', 'Delivery Field'),
    ('endpoint_field', 'Endpoint Field'),
    ('company_field', 'Company Field'),
    ('partner_field', 'Partner Field'),
    ('context_key', 'Context Key'),
    ('request_field', 'Request Field'),
]

OUTBOUND_CONTEXT_SOURCE_SELECTION = [
    ('literal', 'Literal'),
    ('delivery_field', 'Delivery Field'),
    ('endpoint_field', 'Endpoint Field'),
    ('company_field', 'Company Field'),
    ('partner_field', 'Partner Field'),
]

OUTBOUND_RULE_CONDITION_OPERATOR_SELECTION = [
    ('equals', 'Equals'),
    ('not_equals', 'Does Not Equal'),
    ('is_set', 'Is Set'),
    ('not_set', 'Is Not Set'),
    ('contains', 'Contains'),
]

OUTBOUND_ASSIGNMENT_TARGET_SCOPE_SELECTION = [
    ('request', 'Request'),
    ('header', 'Header'),
    ('payload', 'Payload'),
]