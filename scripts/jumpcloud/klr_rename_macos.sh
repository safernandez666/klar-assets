#!/bin/bash
#
# KLR Endpoint Rename — macOS
# Run as root from JumpCloud
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log_info()  { echo "[INFO]  $*"; }
log_warn()  { echo "[WARN]  $*" >&2; }
log_error() { echo "[ERROR] $*" >&2; }

# ---------------------------------------------------------------------------
# Timezone detection (robust, no external APIs)
# ---------------------------------------------------------------------------
get_timezone() {
    local tz=""

    # Preferred: symlink target under /var/db/timezone/zoneinfo/
    if [[ -L /etc/localtime ]]; then
        tz=$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||' || true)
    fi

    # Fallback: systemsetup (requires root, works on physical Macs)
    if [[ -z "$tz" ]]; then
        tz=$(systemsetup -gettimezone 2>/dev/null | sed 's/^Time Zone: //' | tr -d '\n' || true)
    fi

    # Fallback: timedatectl (rare on macOS, but harmless)
    if [[ -z "$tz" ]]; then
        tz=$(timedatectl 2>/dev/null | awk '/Time zone/{print $3}' | tr -d '\n' || true)
    fi

    if [[ -z "$tz" ]]; then
        log_error "Unable to determine system timezone."
        exit 1
    fi

    printf '%s' "$tz"
}

# ---------------------------------------------------------------------------
# Country mapping from timezone
# ---------------------------------------------------------------------------
map_country() {
    local tz="$1"

    # Argentina
    if [[ "$tz" == America/Argentina/* ]] || [[ "$tz" == "Argentina Standard Time" ]]; then
        echo "AR"; return
    fi

    # México (IANA + Windows names)
    case "$tz" in
        America/Mexico_City|America/Cancun|America/Monterrey|America/Chihuahua|\
America/Mazatlan|America/Tijuana|America/BajaSur|America/Hermosillo|\
America/Merida|America/Ojinaga|America/Matamoros|\
"Central Standard Time (Mexico)"|"Mountain Standard Time (Mexico)"|\
"Pacific Standard Time (Mexico)"|"Eastern Standard Time (Mexico)")
            echo "MX"; return
            ;;
    esac

    # Alemania
    if [[ "$tz" == "Europe/Berlin" ]] || [[ "$tz" == "W. Europe Standard Time" ]]; then
        echo "DE"; return
    fi

    # Anything else
    echo "OT"
}

# ---------------------------------------------------------------------------
# Serial number detection (ioreg preferred, system_profiler fallback)
# ---------------------------------------------------------------------------
get_serial() {
    local serial=""

    serial=$(ioreg -c IOPlatformExpertDevice -d 2 2>/dev/null |
             awk -F'"' '/IOPlatformSerialNumber/{print $(NF-1)}' || true)

    if [[ -z "$serial" ]]; then
        serial=$(system_profiler SPHardwareDataType 2>/dev/null |
                 awk '/Serial Number/{print $NF}' | tr -d '\n' || true)
    fi

    printf '%s' "$serial"
}

# ---------------------------------------------------------------------------
# Force JumpCloud agent re-checkin. Done at the END of this script normally,
# but also on the idempotent path so a re-run on an already-renamed Mac
# still nudges JC's inventory in case `hostname`/`displayName` got out of
# sync (e.g., script ran before this fix landed).
#
# JC ships several launchd labels and the names vary by version
# (com.jumpcloud.darwin-agent, com.jumpcloud.agent-updater, etc.) — so
# instead of hardcoding a label, we discover every system-level JC plist
# in /Library/LaunchDaemons/ and kick each one.
# ---------------------------------------------------------------------------
kick_jc_agent() {
    log_info "Forcing JumpCloud agent re-checkin so console reflects the new hostname."

    local plist label kicked=0
    for plist in /Library/LaunchDaemons/com.jumpcloud.*.plist; do
        [[ -e "$plist" ]] || continue
        label=$(/usr/libexec/PlistBuddy -c "Print :Label" "$plist" 2>/dev/null || true)
        [[ -z "$label" ]] && continue
        if launchctl kickstart -k "system/$label" 2>/dev/null; then
            log_info "  kicked: $label"
            kicked=$((kicked + 1))
        fi
    done

    if [[ "$kicked" -eq 0 ]]; then
        log_warn "No JumpCloud daemons found in /Library/LaunchDaemons/. Skipping kick."
    else
        log_info "JC: $kicked daemon(s) kicked. Console hostname should refresh on next inventory."
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
TZ=$(get_timezone)
COUNTRY=$(map_country "$TZ")
OS_LETTER="M"   # macOS

SERIAL=$(get_serial)
SERIAL_CLEAN=$(printf '%s' "$SERIAL" | tr -d '\n')

# Validate serial
if [[ -z "$SERIAL_CLEAN" ]] || [[ "${#SERIAL_CLEAN}" -lt 4 ]]; then
    log_error "Serial number missing or too short (len=${#SERIAL_CLEAN}): '$SERIAL_CLEAN'"
    exit 1
fi

# Extract last 4 chars, uppercase
LAST4=$(printf '%s' "$SERIAL_CLEAN" | awk '{print substr($0, length-3)}' | tr '[:lower:]' '[:upper:]')

NEW_NAME="KLR-${COUNTRY}${OS_LETTER}-${LAST4}"

# Validate computed name length (DNS/NetBIOS friendly)
if [[ "${#NEW_NAME}" -gt 15 ]]; then
    log_error "Computed name exceeds 15 chars: '$NEW_NAME'"
    exit 1
fi

# Idempotency check
CURRENT_COMPUTER_NAME=$(scutil --get ComputerName 2>/dev/null | tr -d '\n' || true)
if [[ "$CURRENT_COMPUTER_NAME" == "$NEW_NAME" ]]; then
    log_info "Hostname already correct: $NEW_NAME"
    kick_jc_agent  # still nudge JC so displayName/hostname reconcile
    exit 0
fi

log_info "Timezone detected:  $TZ"
log_info "Country code:       $COUNTRY"
log_info "Serial (last 4):    $LAST4"
log_info "Previous name:      ${CURRENT_COMPUTER_NAME:-<empty>}"
log_info "New name:           $NEW_NAME"

# Apply rename via scutil (ComputerName, HostName, LocalHostName)
scutil --set ComputerName   "$NEW_NAME"
scutil --set HostName       "$NEW_NAME"
scutil --set LocalHostName  "$NEW_NAME"

# Verify
VERIFY=$(scutil --get ComputerName 2>/dev/null | tr -d '\n' || true)
if [[ "$VERIFY" == "$NEW_NAME" ]]; then
    log_info "Rename successful. No reboot required."
else
    log_error "Rename verification failed. Expected '$NEW_NAME', got '$VERIFY'."
    exit 1
fi

kick_jc_agent

log_info "NOTE: JC 'displayName' is set at enrollment and is sticky."
log_info "      klar_assets reconciles it automatically on the next sync cycle."
