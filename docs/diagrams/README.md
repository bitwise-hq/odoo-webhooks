# Webhooks Diagrams

Mermaid sources in this folder are the single source of truth. Render them to SVG/PNG for README and Odoo Apps.

## Export (Mermaid CLI)

Prerequisite: Node.js 18+.

Example:

npx @mermaid-js/mermaid-cli -i docs/diagrams/webhooks-inbound-flow.mmd -o bwt_webhooks_inbound/static/description/diagrams/webhooks-inbound-flow.svg

Run render.ps1 to export all diagrams.
