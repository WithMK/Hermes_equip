$commands = @("git", "py")
$results = foreach ($name in $commands) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    [pscustomobject]@{ name = $name; available = $null -ne $command; path = if ($command) { $command.Source } else { $null } }
}

[pscustomobject]@{
    timestamp = (Get-Date).ToUniversalTime().ToString("o")
    windows = [Environment]::OSVersion.VersionString
    powershell = $PSVersionTable.PSVersion.ToString()
    architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    prerequisites = $results
} | ConvertTo-Json -Depth 6

if ($results.available -contains $false) { exit 1 }

