param(
    [Parameter(Mandatory = $true)]
    [string]$EquipmentRagBaseUrl,
    [string]$ContextManagerBaseUrl = "",
    [string]$Query = "Loader Vacuum Sensor",
    [string]$SessionId = "hermes-poc-smoke",
    [string]$ContextHealthPath = "/health",
    [string]$ContextGetPath = "/context",
    [string]$ContextResolvePath = "/context/resolve-entity"
)

$arguments = @(
    "-m", "hermes_equipment_poc.check_connections",
    "--equipment-rag-base-url", $EquipmentRagBaseUrl,
    "--query", $Query,
    "--session-id", $SessionId,
    "--context-health-path", $ContextHealthPath,
    "--context-get-path", $ContextGetPath,
    "--context-resolve-path", $ContextResolvePath
)

if ($ContextManagerBaseUrl) {
    $arguments += @("--context-manager-base-url", $ContextManagerBaseUrl)
}

& py @arguments
exit $LASTEXITCODE
