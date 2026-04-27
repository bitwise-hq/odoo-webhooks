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
    @{ input = "webhooks-core-entities.mmd"; output = "bwt_webhooks_core\static\description\diagrams\webhooks-core-entities" },
    @{ input = "webhooks-inbound-flow.mmd"; output = "bwt_webhooks_inbound\static\description\diagrams\webhooks-inbound-flow" },
    @{ input = "webhooks-inbound-sequence.mmd"; output = "bwt_webhooks_inbound\static\description\diagrams\webhooks-inbound-sequence" },
    @{ input = "webhooks-outbound-flow.mmd"; output = "bwt_webhooks_outbound\static\description\diagrams\webhooks-outbound-flow" },
    @{ input = "webhooks-outbound-sequence.mmd"; output = "bwt_webhooks_outbound\static\description\diagrams\webhooks-outbound-sequence" }
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
