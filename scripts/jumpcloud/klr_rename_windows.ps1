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

# ---------------------------------------------------------------------------
# Force JumpCloud agent restart. Always called — even on the idempotent path
# where the rename is a no-op — so that JC's `hostname` field reconciles
# in case it lagged behind a previous run.
# ---------------------------------------------------------------------------
function Restart-JCAgent {
    Write-LogInfo "Restarting JumpCloud agent so the console picks up the new hostname."
    try {
        Restart-Service -Name 'JumpCloud-agent' -Force -ErrorAction Stop
        Write-LogInfo "JC agent restarted. Console hostname should refresh on next inventory."
    } catch {
        Write-LogWarn "Could not restart JumpCloud-agent service: $($_.Exception.Message)"
    }
}

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

# Idempotency
if ($currentName -eq $newName) {
    Write-LogInfo "Computer name already correct: $newName"
    Restart-JCAgent  # still nudge JC so displayName/hostname reconcile
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

Restart-JCAgent

Write-LogInfo "NOTE: JC 'displayName' is set at enrollment and is sticky."
Write-LogInfo "      klar_assets reconciles it automatically on the next sync cycle."
