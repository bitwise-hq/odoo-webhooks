# Webhooks Diagrams

Mermaid sources in this folder are the single source of truth. Render them to SVG/PNG for README and Odoo Apps.

## Diagram Sources

- `webhooks-core-sequence.mmd`
- `webhooks-core-entities.mmd`
- `webhooks-inbound-flow.mmd`
- `webhooks-inbound-sequence.mmd`
- `webhooks-outbound-flow.mmd`
- `webhooks-outbound-sequence.mmd`
- `webhooks-outbound-pipeline.mmd`
- `webhooks-connector-core-sequence.mmd`
- `webhooks-connector-inbound-sequence.mmd`
- `webhooks-connector-outbound-sequence.mmd`
- `webhooks-connector-backend-linking.mmd`
- `webhooks-connector-outbound-routing.mmd`

## Export (Mermaid CLI)

Prerequisite: Node.js 18+.

Example:

npx @mermaid-js/mermaid-cli -i docs/diagrams/webhooks-inbound-flow.mmd -o bwt_webhooks_inbound/static/description/diagrams/webhooks-inbound-flow.svg

Run `render.ps1` to export all diagrams.

The script writes both `.svg` and `.png` outputs into each addon's
`static/description/diagrams/` folder.
