param(
    [Parameter(Mandatory = $true)]
    [string]$EquipmentRagBaseUrl,
    [string]$ContextManagerBaseUrl = "",
    [string]$Query = "Loader Vacuum Sensor",
    [string]$ContextHealthPath = "/health",
    [string]$ContextChatPath = "/v1/chat/completions",
    [string]$ContextModel = "REPLACE_MODEL_NAME"
)

$arguments = @(
    "-m", "hermes_equipment_poc.check_connections",
    "--equipment-rag-base-url", $EquipmentRagBaseUrl,
    "--query", $Query,
    "--context-health-path", $ContextHealthPath,
    "--context-chat-path", $ContextChatPath,
    "--context-model", $ContextModel
)

if ($ContextManagerBaseUrl) {
    $arguments += @("--context-manager-base-url", $ContextManagerBaseUrl)
}

& py @arguments
exit $LASTEXITCODE
