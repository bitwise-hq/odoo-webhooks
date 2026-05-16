$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$diagrams = Join-Path $repoRoot "docs\diagrams"

function Render-Diagram {
    param(
        [string]$InputFile,
        [string]$OutputBase
    )

    npx @mermaid-js/mermaid-cli -i $InputFile -o ($OutputBase + ".svg")
    npx @mermaid-js/mermaid-cli -i $InputFile -o ($OutputBase + ".png")
}

$targets = @(
    @{ input = "webhooks-core-sequence.mmd"; output = "bwt_webhooks_core\static\description\diagrams\webhooks-core-sequence" },
    @{ input = "webhooks-core-entities.mmd"; output = "bwt_webhooks_core\static\description\diagrams\webhooks-core-entities" },
    @{ input = "webhooks-inbound-flow.mmd"; output = "bwt_webhooks_inbound\static\description\diagrams\webhooks-inbound-flow" },
    @{ input = "webhooks-inbound-sequence.mmd"; output = "bwt_webhooks_inbound\static\description\diagrams\webhooks-inbound-sequence" },
    @{ input = "webhooks-outbound-flow.mmd"; output = "bwt_webhooks_outbound\static\description\diagrams\webhooks-outbound-flow" },
    @{ input = "webhooks-outbound-sequence.mmd"; output = "bwt_webhooks_outbound\static\description\diagrams\webhooks-outbound-sequence" },
    @{ input = "webhooks-outbound-pipeline.mmd"; output = "bwt_webhooks_outbound\static\description\diagrams\webhooks-outbound-pipeline" },
    @{ input = "webhooks-connector-core-sequence.mmd"; output = "bwt_connector_webhooks_core\static\description\diagrams\webhooks-connector-core-sequence" },
    @{ input = "webhooks-connector-backend-linking.mmd"; output = "bwt_connector_webhooks_core\static\description\diagrams\webhooks-connector-backend-linking" },
    @{ input = "webhooks-connector-inbound-sequence.mmd"; output = "bwt_connector_webhooks_inbound\static\description\diagrams\webhooks-connector-inbound-sequence" },
    @{ input = "webhooks-connector-backend-linking.mmd"; output = "bwt_connector_webhooks_inbound\static\description\diagrams\webhooks-connector-backend-linking" },
    @{ input = "webhooks-connector-outbound-sequence.mmd"; output = "bwt_connector_webhooks_outbound\static\description\diagrams\webhooks-connector-outbound-sequence" },
    @{ input = "webhooks-connector-outbound-routing.mmd"; output = "bwt_connector_webhooks_outbound\static\description\diagrams\webhooks-connector-outbound-routing" }
)

foreach ($item in $targets) {
    $inputPath = Join-Path $diagrams $item.input
    $outputBase = Join-Path $repoRoot $item.output

    $outputDir = Split-Path $outputBase -Parent
    if (-not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir | Out-Null
    }

    Render-Diagram -InputFile $inputPath -OutputBase $outputBase
}
