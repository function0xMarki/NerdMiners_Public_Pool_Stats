#!/bin/bash
# =============================================================================
# NerdMiners_Public_Pool_Stats Bot - Auto Update
# Called automatically by NerdMiners_Bot.py on each execution.
# Checks the remote repository for changes, updates local files,
# preserves user configuration, and sends Telegram notifications.
#
# NOTE: The entire script is wrapped in main() so that bash parses the full
# file before executing anything.  This prevents issues if git pull replaces
# this script while it is running.
# =============================================================================

main() {

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOGS_DIR="$SCRIPT_DIR/Logs"
LOG_FILE="$LOGS_DIR/NerdMiners_Public_Pool_Stats_Bot.log"
LOCK_FILE="$SCRIPT_DIR/.update.lock"
CONFIG_FILE="$SCRIPT_DIR/config.py"
CONFIG_BACKUP="$SCRIPT_DIR/.config.py.bak"
ENV_FILE="$SCRIPT_DIR/.env"
BRANCH="main"

# Ensure Logs directory exists
mkdir -p "$LOGS_DIR"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - UPDATE - $1" >> "$LOG_FILE"
}

# Load a variable value from .env (strips surrounding whitespace)
load_env_var() {
    local VAR_NAME="$1"
    grep -E "^${VAR_NAME}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d'=' -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

send_telegram() {
    local MESSAGE="$1"
    local BOT_TOKEN CHAT_ID

    BOT_TOKEN=$(load_env_var "BOT_TOKEN")
    CHAT_ID=$(load_env_var "CHAT_ID")

    if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
        log "Cannot send Telegram notification: BOT_TOKEN or CHAT_ID missing"
        return 1
    fi

    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" \
        -d "text=${MESSAGE}" \
        -d "parse_mode=HTML" \
        > /dev/null 2>&1
}

# Extract variable names from config.py (lines matching: VARNAME = value)
get_variable_names() {
    local FILE="$1"
    grep -E '^[A-Z][A-Z_0-9]+ = ' "$FILE" | sed 's/ = .*//'
}

# Save all variable assignment lines from config.py
save_config_variables() {
    local FILE="$1"
    local DEST="$2"
    grep -E '^[A-Z][A-Z_0-9]+ = ' "$FILE" > "$DEST"
}

# Restore saved variables into the new config.py (line-by-line rebuild).
# Variables that existed before are restored with user values.
# New variables (not in backup) keep the repo default.
# Comments, docstrings, and blank lines come from the new repo version.
restore_config_variables() {
    local CONFIG="$1"
    local SAVE_FILE="$2"
    local TEMP_CONFIG="${CONFIG}.tmp"

    # Remove temp file if it exists from a previous failed run
    rm -f "$TEMP_CONFIG"

    while IFS= read -r CONFIG_LINE || [ -n "$CONFIG_LINE" ]; do
        # Check if this line is a variable assignment
        VAR_NAME=""
        if echo "$CONFIG_LINE" | grep -qE '^[A-Z][A-Z_0-9]+ = '; then
            VAR_NAME=$(echo "$CONFIG_LINE" | sed 's/ = .*//')
        fi

        if [ -n "$VAR_NAME" ]; then
            # Look for a saved value for this variable
            SAVED_LINE=$(grep -E "^${VAR_NAME} = " "$SAVE_FILE" 2>/dev/null | head -1)
            if [ -n "$SAVED_LINE" ]; then
                # Restore user's value
                printf '%s\n' "$SAVED_LINE" >> "$TEMP_CONFIG"
            else
                # New variable — keep the default from the repo
                printf '%s\n' "$CONFIG_LINE" >> "$TEMP_CONFIG"
            fi
        else
            # Comment, blank line, docstring — keep as-is from the repo
            printf '%s\n' "$CONFIG_LINE" >> "$TEMP_CONFIG"
        fi
    done < "$CONFIG"

    mv "$TEMP_CONFIG" "$CONFIG"
}

# ---------------------------------------------------------------------------
# Lock management
# ---------------------------------------------------------------------------

cleanup() {
    rm -f "$LOCK_FILE"
}

# Clean stale lock (older than 5 minutes)
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo "0") ))
    if [ "$LOCK_AGE" -gt 300 ]; then
        log "Removing stale lock file (age: ${LOCK_AGE}s)"
        rm -f "$LOCK_FILE"
    else
        # Another update is running — exit silently
        return 0
    fi
fi

# Acquire lock
echo $$ > "$LOCK_FILE"
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Check for updates
# ---------------------------------------------------------------------------

# Verify this is a git repository
if [ ! -d "$SCRIPT_DIR/.git" ]; then
    log "Not a git repository. Skipping update check."
    return 0
fi

# Verify git is available
if ! command -v git &>/dev/null; then
    log "git is not installed. Skipping update check."
    return 0
fi

# Fetch latest changes from remote
if ! git -C "$SCRIPT_DIR" fetch origin 2>> "$LOG_FILE"; then
    log "git fetch failed (network error?). Skipping update."
    return 0
fi

# Compare local HEAD with remote
LOCAL_HASH=$(git -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null)
REMOTE_HASH=$(git -C "$SCRIPT_DIR" rev-parse "origin/${BRANCH}" 2>/dev/null)

if [ -z "$LOCAL_HASH" ] || [ -z "$REMOTE_HASH" ]; then
    log "Could not determine local or remote hash. Skipping update."
    return 0
fi

if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    # Already up to date — fast path
    return 0
fi

# ---------------------------------------------------------------------------
# Update available — apply changes
# ---------------------------------------------------------------------------

log "Update available: ${LOCAL_HASH:0:7} -> ${REMOTE_HASH:0:7}"

# Check which files changed (for requirements.txt detection)
CHANGED_FILES=$(git -C "$SCRIPT_DIR" diff --name-only "$LOCAL_HASH" "$REMOTE_HASH" 2>/dev/null)
log "Changed files: $(echo "$CHANGED_FILES" | tr '\n' ' ')"

REQUIREMENTS_CHANGED=false
if echo "$CHANGED_FILES" | grep -q "^requirements.txt$"; then
    REQUIREMENTS_CHANGED=true
fi

# Save user configuration from config.py
if [ -f "$CONFIG_FILE" ]; then
    log "Saving user configuration..."
    save_config_variables "$CONFIG_FILE" "$CONFIG_BACKUP"
    OLD_VARS=$(get_variable_names "$CONFIG_FILE")
else
    OLD_VARS=""
fi

# Apply remote changes — reset always wins (no merge conflicts possible)
# Untracked files (.env, database, logs) are not affected by reset --hard
log "Applying update from origin/${BRANCH}..."
if ! git -C "$SCRIPT_DIR" reset --hard "origin/${BRANCH}" 2>> "$LOG_FILE"; then
    log "ERROR: git reset --hard failed."
    send_telegram "⚠️ <b>Bot Update Failed</b>%0A%0AThe automatic update could not be applied — git reset failed.%0A%0AYour configuration backup is safe at:%0A<code>${SCRIPT_DIR}/.config.py.bak</code>%0A%0A⚡ <b>To fix, connect to your server and run:</b>%0A<code>git -C ${SCRIPT_DIR} status</code>%0A<code>git -C ${SCRIPT_DIR} reset --hard origin/main</code>"
    return 1
fi

# Ensure all shell scripts are executable after pull
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null

# Detect new variables in the updated config.py
ADDED_VARS=""
if [ -f "$CONFIG_FILE" ]; then
    NEW_VARS=$(get_variable_names "$CONFIG_FILE")

    for VAR in $NEW_VARS; do
        IS_NEW=true
        for OLD_VAR in $OLD_VARS; do
            if [ "$VAR" = "$OLD_VAR" ]; then
                IS_NEW=false
                break
            fi
        done

        if [ "$IS_NEW" = true ]; then
            DEFAULT_VALUE=$(grep -E "^${VAR} = " "$CONFIG_FILE" | head -1 | sed "s/^${VAR} = //")
            if [ -n "$ADDED_VARS" ]; then
                ADDED_VARS="${ADDED_VARS}%0A"
            fi
            ADDED_VARS="${ADDED_VARS}  • <code>${VAR}</code> = ${DEFAULT_VALUE}"
        fi
    done
fi

# Restore user configuration into the new config.py
if [ -f "$CONFIG_BACKUP" ] && [ -f "$CONFIG_FILE" ]; then
    log "Restoring user configuration..."
    restore_config_variables "$CONFIG_FILE" "$CONFIG_BACKUP"
    rm -f "$CONFIG_BACKUP"
    log "User configuration restored."
fi

# Reinstall dependencies if requirements.txt changed
if [ "$REQUIREMENTS_CHANGED" = true ]; then
    log "requirements.txt changed. Reinstalling dependencies..."
    if "$SCRIPT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" --quiet 2>> "$LOG_FILE"; then
        log "Dependencies updated successfully."
    else
        log "WARNING: pip install failed."
        send_telegram "⚠️ <b>Dependency Update Failed</b>%0A%0AThe update changed requirements.txt, but pip failed to install the new packages. The bot will continue running with the previous dependency versions.%0A%0A⚡ <b>To fix manually, connect to your server and run:</b>%0A<code>${SCRIPT_DIR}/venv/bin/pip install -r ${SCRIPT_DIR}/requirements.txt</code>%0A%0ALogs: <code>${LOG_FILE}</code>"
    fi
fi

# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

COMMIT_MSG=$(git -C "$SCRIPT_DIR" log -1 --pretty=format:"%h - %s" 2>/dev/null)

send_telegram "🔄 <b>Bot Updated Successfully</b>%0A%0A📦 <code>${COMMIT_MSG}</code>%0A%0AThe bot has been updated. Changes will be applied on the next scheduled run."
log "Update notification sent."

if [ -n "$ADDED_VARS" ]; then
    send_telegram "⚙️ <b>New Configuration Options</b>%0A%0AThe latest update added new settings to config.py. They are active with their default values — no action needed unless you want to customize them.%0A%0A${ADDED_VARS}%0A%0ATo change them, edit config.py on your server."
    log "New variables notification sent."
fi

log "Update completed successfully."
return 0

}

# Run main — the function is fully parsed before execution begins
main "$@"
exit $?
