HTTP_METHOD_SELECTION = [
    ('post', 'POST'),
    ('put', 'PUT'),
    ('patch', 'PATCH'),
]

INBOUND_ACTION_SELECTION = [
    ('done', 'Mark Done'),
    ('dead_letter', 'Dead Letter'),
    ('retry', 'Retry'),
    ('create_record', 'Create Record'),
    ('update_record', 'Update Record'),
    ('upsert_record', 'Upsert Record'),
    ('queue_outbound', 'Queue Outbound'),
]

INBOUND_SOURCE_KIND_SELECTION = [
    ('resolved_value', 'Resolved Value'),
    ('semantic_field', 'Semantic Field'),
    ('event_field', 'Event Field'),
    ('literal', 'Literal'),
]

INBOUND_RULE_CONDITION_OPERATOR_SELECTION = [
    ('equals', 'Equals'),
    ('not_equals', 'Does Not Equal'),
    ('is_set', 'Is Set'),
    ('not_set', 'Is Not Set'),
    ('contains', 'Contains'),
]

INBOUND_ASSIGNMENT_TARGET_KIND_SELECTION = [
    ('field', 'Record Field'),
    ('context_key', 'Outbound Context Key'),
]

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