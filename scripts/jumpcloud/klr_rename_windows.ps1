#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Renombra el endpoint Windows a la nomenclatura KLR.
.DESCRIPTION
    KLR-<COUNTRY><OS>-<LAST4SERIAL>
    Ejecutar como SYSTEM desde JumpCloud.
#>

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
function Write-LogInfo  { param([string]$m) Write-Host "[INFO]  $m" }
function Write-LogWarn  { param([string]$m) Write-Warning "[WARN]  $m" }
function Write-LogError { param([string]$m) Write-Error "[ERROR] $m"; exit 1 }

# NOTE: We deliberately do NOT call Restart-Service -Name 'JumpCloud-agent'
# here. The rename script runs *inside* the JumpCloud agent's process tree,
# so restarting it before the script exits kills our own stdout/stderr and
# JC never receives a commandresult — the run looks like it never happened
# (no exit code, no output). On Windows the rename is pending until reboot
# anyway, so kicking the agent doesn't buy us anything; the next inventory
# cycle (or the post-reboot connect) will pick up the new hostname on its
# own.

# ---------------------------------------------------------------------------
# Country mapping from Windows TimeZone
# ---------------------------------------------------------------------------
function Get-CountryCode {
    param([string]$TzId, [string]$TzStandardName)

    # Argentina
    if ($TzId -like "America/Argentina/*" -or
        $TzId -eq "Argentina Standard Time" -or
        $TzStandardName -eq "Argentina Standard Time") {
        return "AR"
    }

    # México (IANA + Windows names)
    $mxZones = @(
        "America/Mexico_City","America/Cancun","America/Monterrey",
        "America/Chihuahua","America/Mazatlan","America/Tijuana",
        "America/BajaSur","America/Hermosillo","America/Merida",
        "America/Ojinaga","America/Matamoros",
        "Central Standard Time (Mexico)","Mountain Standard Time (Mexico)",
        "Pacific Standard Time (Mexico)","Eastern Standard Time (Mexico)"
    )
    if ($mxZones -contains $TzId -or $mxZones -contains $TzStandardName) {
        return "MX"
    }

    # Alemania
    if ($TzId -eq "Europe/Berlin" -or
        $TzId -eq "W. Europe Standard Time" -or
        $TzStandardName -eq "W. Europe Standard Time") {
        return "DE"
    }

    return "OT"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
$tz = Get-TimeZone
$country = Get-CountryCode -TzId $tz.Id -TzStandardName $tz.StandardName
$osLetter = "W"   # Windows

# Serial number via WMI
$serialObj = Get-CimInstance Win32_BIOS -ErrorAction Stop
$serial = $serialObj.SerialNumber
$serialClean = ($serial -as [string]).Trim()

# Reject known placeholder serials
$invalidSerials = @(
    'To Be Filled By O.E.M.'
    'System Serial Number'
    'Not Available'
    'None'
    ''
)

if ($serialClean.Length -lt 5 -or $invalidSerials -contains $serialClean) {
    Write-LogError "Serial number invalid or too short: '$serialClean'"
}

# Extract last 5 chars to avoid serial-suffix collisions across the fleet
# (Apple-style serials of the same generation can share their last 4 chars,
# but rarely their last 5).
$last5 = ($serialClean.ToUpper())[-5..-1] -join ''
$newName = "KLR-$country$osLetter-$last5"

# NetBIOS limit = 15 chars
if ($newName.Length -gt 15) {
    Write-LogError "Computed name exceeds 15 chars: '$newName'"
}

$currentName = $env:COMPUTERNAME

# Idempotency — if it ALREADY starts with KLR- we leave it alone even if the
# computed $newName differs (avoids re-renaming a user who travels and the
# detected timezone changes).
if ($currentName -match '^KLR-') {
    Write-LogInfo "Already has KLR-* prefix: $currentName (skipping)"
    exit 0
}
if ($currentName -eq $newName) {
    Write-LogInfo "Computer name already correct: $newName"
    exit 0
}

Write-LogInfo "Timezone detected:  $($tz.Id) ($($tz.StandardName))"
Write-LogInfo "Country code:       $country"
Write-LogInfo "Serial (last 5):    $last5"
Write-LogInfo "Previous name:      $currentName"
Write-LogInfo "New name:           $newName"
Write-LogWarn "This change requires a reboot to fully propagate."

Rename-Computer -NewName $newName -Force -ErrorAction Stop

Write-LogInfo "Rename command executed successfully."
Write-LogInfo "Please schedule or perform a reboot when convenient."

# ---------------------------------------------------------------------------
# Update JumpCloud console `displayName` to match the new hostname.
# Without this, the JC console keeps showing the original enrollment-time
# displayName forever (it never auto-refreshes from `hostname`).
#
# Requires the JC Command to expose JC_API_KEY as an environment variable
# (Command → Environment Variables tab in JC console). The key only needs
# Systems: read+write scope.
# ---------------------------------------------------------------------------
function Update-JcDisplayName {
    param([string]$NewName)

    if ([string]::IsNullOrWhiteSpace($env:JC_API_KEY)) {
        Write-LogWarn "JC_API_KEY env var not set on the command — skipping displayName PATCH."
        Write-LogWarn "Set it under JC Command -> Environment Variables. klar_assets sync will reconcile within 6h."
        return
    }

    # Resolve systemKey from JC agent config
    $confPaths = @(
        "$env:ProgramData\JumpCloud\Plugins\Contrib\jcagent.conf",
        "$env:ProgramFiles\JumpCloud\Plugins\Contrib\jcagent.conf"
    )
    $systemId = $null
    foreach ($p in $confPaths) {
        if (Test-Path $p) {
            try {
                $cfg = Get-Content $p -Raw | ConvertFrom-Json
                if ($cfg.systemKey) { $systemId = $cfg.systemKey; break }
            } catch { }
        }
    }

    if ([string]::IsNullOrWhiteSpace($systemId)) {
        Write-LogWarn "Could not resolve JC systemKey from agent config — skipping displayName PATCH."
        return
    }

    $body = @{ displayName = $NewName } | ConvertTo-Json -Compress
    try {
        $resp = Invoke-WebRequest -Uri "https://console.jumpcloud.com/api/systems/$systemId" `
            -Method Put `
            -Headers @{ "x-api-key" = $env:JC_API_KEY; "Content-Type" = "application/json"; "Accept" = "application/json" } `
            -Body $body `
            -TimeoutSec 15 `
            -UseBasicParsing
        if ($resp.StatusCode -eq 200) {
            Write-LogInfo "JC displayName PATCH OK ($NewName)."
        } else {
            Write-LogWarn "JC displayName PATCH unexpected status: $($resp.StatusCode)"
        }
    } catch {
        Write-LogWarn "JC displayName PATCH failed: $($_.Exception.Message). klar_assets sync will reconcile."
    }
}

Update-JcDisplayName -NewName $newName

Write-LogInfo "NOTE: Hostname won't be visible in JC until after the reboot."
