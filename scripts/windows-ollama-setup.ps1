[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$MacAddress,

    [string]$Model = "qwen3.5:9b",

    [switch]$InstallOllama,

    [switch]$RestartOllama
)

$ErrorActionPreference = "Stop"
$ruleName = "Local Context Forge - Ollama from Mac"

try {
    $parsedAddress = [System.Net.IPAddress]::Parse($MacAddress)
}
catch {
    throw "-MacAddress must be one IPv4 address, not 'Any' or a broad CIDR."
}
if ($parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw "-MacAddress must be IPv4 because OLLAMA_HOST is configured as 0.0.0.0:11434."
}
$octets = $parsedAddress.GetAddressBytes()
$isRfc1918 = (
    $octets[0] -eq 10 -or
    ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) -or
    ($octets[0] -eq 192 -and $octets[1] -eq 168)
)
$isCgnatTunnel = (
    $octets[0] -eq 100 -and $octets[1] -ge 64 -and $octets[1] -le 127
)
$isForbidden = (
    $parsedAddress.IPAddressToString -eq "0.0.0.0" -or
    $parsedAddress.IPAddressToString -eq "255.255.255.255" -or
    $octets[0] -eq 127 -or
    ($octets[0] -ge 224 -and $octets[0] -le 239)
)
if ($isForbidden -or (-not $isRfc1918 -and -not $isCgnatTunnel)) {
    throw "-MacAddress must be the Mac's single private IPv4 address (RFC1918 or 100.64.0.0/10 tunnel range); Any, loopback, multicast, 255.255.255.255, and public addresses are refused. Validate subnet-specific network/broadcast addresses yourself."
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "Run this script from an Administrator PowerShell so it can create a scoped firewall rule."
}

$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaCommand) {
    if (-not $InstallOllama) {
        throw "Ollama was not found. Install it from https://ollama.com/download/windows or rerun with -InstallOllama."
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is unavailable. Install Ollama manually from the official download page."
    }
    if ($PSCmdlet.ShouldProcess("Ollama.Ollama", "Install with winget")) {
        winget install --exact --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
    }
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
    $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollamaCommand) {
        throw "Ollama installation finished but the executable is not in this PowerShell PATH. Open a new Administrator PowerShell and rerun."
    }
}

if ($PSCmdlet.ShouldProcess("Current user environment", "Set Ollama LAN listener and single-request concurrency")) {
    [Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")
    [Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "1", "User")
    $env:OLLAMA_HOST = "0.0.0.0:11434"
    $env:OLLAMA_NUM_PARALLEL = "1"
}

$existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existingRule) {
    if ($PSCmdlet.ShouldProcess($ruleName, "Restrict existing firewall rule to $parsedAddress")) {
        $existingRule | Set-NetFirewallRule `
            -Enabled True `
            -Direction Inbound `
            -Action Allow `
            -Profile Private
        $existingRule | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress $parsedAddress.IPAddressToString
        $existingRule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort 11434
    }
}
else {
    if ($PSCmdlet.ShouldProcess($ruleName, "Create firewall rule restricted to $parsedAddress")) {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Description "Allow Local Context Forge on one trusted Mac to reach Ollama. Do not broaden to Any." `
            -Enabled True `
            -Direction Inbound `
            -Action Allow `
            -Profile Private `
            -Protocol TCP `
            -LocalPort 11434 `
            -RemoteAddress $parsedAddress.IPAddressToString | Out-Null
    }
}

if ($RestartOllama) {
    if ($PSCmdlet.ShouldProcess("Ollama", "Restart so OLLAMA_HOST takes effect")) {
        Get-Process ollama -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Process -FilePath $ollamaCommand.Source -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 3
    }
}
else {
    Write-Warning "Restart Ollama after this script so OLLAMA_HOST=0.0.0.0:11434 takes effect. Rerun with -RestartOllama to do that now."
}

if ($PSCmdlet.ShouldProcess($Model, "Pull Ollama model")) {
    & $ollamaCommand.Source pull $Model
    if ($LASTEXITCODE -ne 0) {
        throw "ollama pull failed for '$Model'. Verify the exact model tag in the current Ollama catalog; the script will not silently substitute another model."
    }
}

Write-Host ""
Write-Host "Configured Ollama for a private LAN connection."
Write-Host "Allowed remote address: $($parsedAddress.IPAddressToString)"
Write-Host "Firewall profile: Private only"
Write-Host "Model: $Model"
Write-Host ""
Write-Host "Verify from the Mac:"
Write-Host "  curl --fail http://WINDOWS_PRIVATE_IP:11434/api/tags"
Write-Host "Do not create a router port-forward for TCP 11434."
