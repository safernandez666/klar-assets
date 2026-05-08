#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Programa un reinicio para hoy (o mañana) a las 22:00 hora local.
.DESCRIPTION
    Si las 22:00 ya pasaron, programa para mañana.
    No ejecuta el reinicio inmediatamente.
    Si ya hay un reinicio pendiente, informa y sale sin duplicar.
#>

function Write-LogInfo  { param([string]$m) Write-Host "[INFO]  $m" }
function Write-LogWarn  { param([string]$m) Write-Warning "[WARN]  $m" }
function Write-LogError { param([string]$m) Write-Error "[ERROR] $m"; exit 1 }

$targetHour = 22
$now = Get-Date

# Build target DateTime for today at 22:00
$targetToday = Get-Date -Year $now.Year -Month $now.Month -Day $now.Day `
                -Hour $targetHour -Minute 0 -Second 0 -Millisecond 0

if ($now -ge $targetToday) {
    $target = $targetToday.AddDays(1)
} else {
    $target = $targetToday
}

$seconds = [math]::Round(($target - $now).TotalSeconds)
# ASCII-only: shutdown.exe receives /c via argv as ANSI/codepage on Windows.
# PowerShell sends UTF-8, so accented chars (á, ó, ñ) render as mojibake
# (`á` -> `Ã¡`, `ó` -> `Ã³`) in the popup. Stick to ASCII to keep it readable
# regardless of the host locale or PowerShell version.
$msg = 'Klar Security reiniciara este equipo a las 22:00 para completar una actualizacion de configuracion. Por favor guarda tu trabajo.'

Write-LogInfo "Current time:       $($now.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-LogInfo "Scheduled reboot:   $($target.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-LogInfo "Seconds until then: $seconds"

# Attempt to schedule shutdown.exe /r
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "shutdown.exe"
$psi.Arguments = "/r /t $seconds /c `"$msg`""
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true

$proc = [System.Diagnostics.Process]::Start($psi)
$proc.WaitForExit()
$stdout = $proc.StandardOutput.ReadToEnd()
$stderr = $proc.StandardError.ReadToEnd()

switch ($proc.ExitCode) {
    0 {
        Write-LogInfo "Reboot scheduled successfully."
        Write-LogInfo "Shutdown.exe output: $stdout"
    }
    1190 {
        Write-LogWarn "A shutdown/reboot is already scheduled."
        Write-LogWarn "No new schedule was created to avoid conflicts."
        exit 0
    }
    1116 {
        Write-LogWarn "Unable to abort because no shutdown was in progress (unexpected)."
        exit 1
    }
    default {
        Write-LogError "shutdown.exe failed (exit code $($proc.ExitCode)). Stderr: $stderr"
    }
}
