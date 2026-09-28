param(
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [Parameter(Mandatory = $true)][string]$Model,
    [string]$ApiKey = "unused"
)

$headers = @{ Authorization = "Bearer $ApiKey"; "Content-Type" = "application/json" }
$body = @{
    model = $Model
    stream = $false
    messages = @(@{ role = "user"; content = "Reply with exactly: HERMES_POC_OK" })
} | ConvertTo-Json -Depth 8

$started = Get-Date
try {
    $response = Invoke-RestMethod -Method Post -Uri "$($BaseUrl.TrimEnd('/'))/chat/completions" -Headers $headers -Body $body -TimeoutSec 120
    [pscustomobject]@{
        ok = $true
        model = $Model
        duration_ms = [int]((Get-Date) - $started).TotalMilliseconds
        content = $response.choices[0].message.content
    } | ConvertTo-Json -Depth 6
}
catch {
    [pscustomobject]@{
        ok = $false
        model = $Model
        duration_ms = [int]((Get-Date) - $started).TotalMilliseconds
        error = $_.Exception.Message
    } | ConvertTo-Json -Depth 6
    exit 1
}

