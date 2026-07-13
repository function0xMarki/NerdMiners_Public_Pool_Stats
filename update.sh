#!/bin/bash
# =============================================================================
# NerdMiners_Public_Pool_Stats Bot - Manual Update
#
# Usage:
#   ./update.sh                  Manual run from the terminal.
#   ./update.sh --from-telegram  Invoked by NerdMiners_Bot.py after an
#                                authorized /update command was received.
#   ./update.sh --auto           Invoked by NerdMiners_Bot.py on every run
#                                when UPDATE_MODE = "auto" in config.py.
#
# Applies the latest version from the remote repository, preserves the user
# configuration in config.py, reinstalls dependencies if needed (through
# install.sh --heal) and sends a Telegram notification with the applied
# commits. Applied changes take effect on the bot's next scheduled run.
#
# NOTE: The entire script is wrapped in main() so that bash parses the full
# file before executing anything.  This prevents issues if git reset replaces
# this script while it is running.
# =============================================================================

main() {

MODE="manual"
case "$1" in
    --from-telegram) MODE="telegram" ;;
    --auto) MODE="auto" ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOGS_DIR="$SCRIPT_DIR/Logs"
LOG_FILE="$LOGS_DIR/NerdMiners_Public_Pool_Stats_Bot.log"
LOCK_FILE="$SCRIPT_DIR/.update.lock"
CONFIG_FILE="$SCRIPT_DIR/config.py"
CONFIG_BACKUP="$SCRIPT_DIR/.config.py.bak"
ENV_FILE="$SCRIPT_DIR/.env"
VERSION_FILE="$SCRIPT_DIR/VERSION"
BRANCH="main"

# Ensure Logs directory exists
mkdir -p "$LOGS_DIR"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - UPDATE - $1" >> "$LOG_FILE"
}

# Print to stdout only on manual terminal runs
say() {
    if [ "$MODE" = "manual" ]; then
        echo "$1"
    fi
}

# Escape &, < and > for Telegram HTML parse mode (stdin -> stdout)
html_escape() {
    sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

# Load a variable value from .env (strips surrounding whitespace)
load_env_var() {
    local VAR_NAME="$1"
    grep -E "^${VAR_NAME}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d'=' -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

# Send a Telegram message. The message may contain real newlines and HTML;
# --data-urlencode encodes it safely (&, %, newlines, etc.).
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
        --data-urlencode "chat_id=${CHAT_ID}" \
        --data-urlencode "text=${MESSAGE}" \
        --data-urlencode "parse_mode=HTML" \
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
    local COUNT
    COUNT=$(wc -l < "$DEST" | tr -d ' ')
    log "Saved $COUNT variable(s) to backup"
}

# Restore saved variables into the new config.py (line-by-line rebuild).
# Variables that existed before are restored with user values.
# New variables (not in backup) keep the repo default.
# Comments, docstrings, and blank lines come from the new repo version.
restore_config_variables() {
    local CONFIG="$1"
    local SAVE_FILE="$2"
    local TEMP_CONFIG="${CONFIG}.tmp"
    local RESTORED=0
    local KEPT_NEW=0

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
                RESTORED=$((RESTORED + 1))
                # Log if the value actually differs from the repo default
                if [ "$SAVED_LINE" != "$CONFIG_LINE" ]; then
                    log "  Restored: $VAR_NAME (user value differs from repo default)"
                fi
            else
                # New variable — keep the default from the repo
                printf '%s\n' "$CONFIG_LINE" >> "$TEMP_CONFIG"
                KEPT_NEW=$((KEPT_NEW + 1))
                log "  New variable kept: $VAR_NAME"
            fi
        else
            # Comment, blank line, docstring — keep as-is from the repo
            printf '%s\n' "$CONFIG_LINE" >> "$TEMP_CONFIG"
        fi
    done < "$CONFIG"

    if ! mv "$TEMP_CONFIG" "$CONFIG"; then
        log "ERROR: mv failed — could not replace config.py with restored version"
        return 1
    fi

    log "Restore summary: $RESTORED variable(s) restored, $KEPT_NEW new variable(s) kept"
}

# ---------------------------------------------------------------------------
# Lock management
# ---------------------------------------------------------------------------

cleanup() {
    rm -f "$LOCK_FILE"
}

# Clean stale lock (older than 5 minutes)
if [ -f "$LOCK_FILE" ]; then
    # stat -c is GNU (Linux), stat -f %m is BSD (macOS)
    LOCK_MTIME=$(stat -c %Y "$LOCK_FILE" 2>/dev/null || stat -f %m "$LOCK_FILE" 2>/dev/null || echo "0")
    LOCK_AGE=$(( $(date +%s) - LOCK_MTIME ))
    if [ "$LOCK_AGE" -gt 300 ]; then
        log "Removing stale lock file (age: ${LOCK_AGE}s)"
        rm -f "$LOCK_FILE"
    else
        say "Another update is already running. Try again in a few minutes."
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
    log "Not a git repository. Cannot update."
    say "ERROR: this installation is not a git repository; cannot update."
    [ "$MODE" = "telegram" ] && send_telegram "⚠️ <b>Update Failed</b>

This installation is not a git repository, so it cannot be updated automatically."
    return 1
fi

# Verify git is available
if ! command -v git &>/dev/null; then
    log "git is not installed. Cannot update."
    say "ERROR: git is not installed."
    [ "$MODE" = "telegram" ] && send_telegram "⚠️ <b>Update Failed</b>

git is not installed on the server."
    return 1
fi

say "Checking for updates..."

# Fetch latest changes from remote
if ! git -C "$SCRIPT_DIR" fetch origin 2>> "$LOG_FILE"; then
    log "git fetch failed (network error?)."
    say "ERROR: could not reach the remote repository (network error?)."
    [ "$MODE" = "telegram" ] && send_telegram "⚠️ <b>Update Failed</b>

Could not reach the remote repository (network error?). Please try again later."
    return 1
fi

# Compare local HEAD with remote
LOCAL_HASH=$(git -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null)
REMOTE_HASH=$(git -C "$SCRIPT_DIR" rev-parse "origin/${BRANCH}" 2>/dev/null)

if [ -z "$LOCAL_HASH" ] || [ -z "$REMOTE_HASH" ]; then
    log "Could not determine local or remote hash. Aborting update."
    say "ERROR: could not determine repository state."
    return 1
fi

CURRENT_VERSION=$(cat "$VERSION_FILE" 2>/dev/null | tr -d '[:space:]')
[ -z "$CURRENT_VERSION" ] && CURRENT_VERSION="unknown"

if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    log "Already up to date (v${CURRENT_VERSION}, ${LOCAL_HASH:0:7})"
    say "Already up to date (v${CURRENT_VERSION})."
    if [ "$MODE" = "telegram" ]; then
        send_telegram "✅ <b>Already Up To Date</b>

The bot is already running the latest version (<b>v${CURRENT_VERSION}</b>)."
    fi
    return 0
fi

# ---------------------------------------------------------------------------
# Update available — apply changes
# ---------------------------------------------------------------------------

log "Update available: ${LOCAL_HASH:0:7} -> ${REMOTE_HASH:0:7} (mode: $MODE)"
say "Update available. Applying..."

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
    say "ERROR: git reset --hard failed. See $LOG_FILE"
    send_telegram "⚠️ <b>Update Failed</b>

The update could not be applied — git reset failed.

Your configuration backup is safe at:
<code>${SCRIPT_DIR}/.config.py.bak</code>

⚡ <b>To fix, connect to your server and run:</b>
<code>git -C ${SCRIPT_DIR} status</code>
<code>git -C ${SCRIPT_DIR} reset --hard origin/main</code>"
    return 1
fi

# Ensure all shell scripts are executable after the reset
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null

NEW_VERSION=$(cat "$VERSION_FILE" 2>/dev/null | tr -d '[:space:]')
[ -z "$NEW_VERSION" ] && NEW_VERSION="unknown"

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
            DEFAULT_VALUE=$(grep -E "^${VAR} = " "$CONFIG_FILE" | head -1 | sed "s/^${VAR} = //" | html_escape)
            if [ -n "$ADDED_VARS" ]; then
                ADDED_VARS="${ADDED_VARS}
"
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

# Repair environment after the update: reinstalls dependencies if
# requirements.txt changed (hash stamp), fixes permissions, etc.
if [ -x "$SCRIPT_DIR/install.sh" ]; then
    say "Verifying environment (dependencies, permissions)..."
    if ! "$SCRIPT_DIR/install.sh" --heal; then
        log "WARNING: install.sh --heal reported a problem after the update."
        send_telegram "⚠️ <b>Dependency Update Failed</b>

The update was applied, but the environment repair (dependencies) failed.
The bot will keep running with the previous dependency versions.

⚡ <b>To fix manually, connect to your server and run:</b>
<code>${SCRIPT_DIR}/install.sh</code>

Logs: <code>${LOG_FILE}</code>"
    fi
fi

# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

# Count total new commits applied
TOTAL_COMMITS=$(git -C "$SCRIPT_DIR" log "$LOCAL_HASH".."$REMOTE_HASH" --oneline 2>/dev/null | wc -l | tr -d ' ')

# Build commit list: subject + short hash always; include the commit body
# (description) when 3 or fewer commits were applied. HTML-escaped.
# Fields are split with bash parameter expansion because commit bodies are
# multi-line and line-based tools (cut/awk) would mix the fields up.
COMMIT_LINES=""
COUNT=0
while IFS= read -r -d $'\x1e' RECORD; do
    RECORD="${RECORD#$'\n'}"   # strip the newline git emits between records
    [ -z "$RECORD" ] && continue
    COUNT=$((COUNT + 1))
    [ "$COUNT" -gt 10 ] && break

    C_HASH="${RECORD%%$'\x1f'*}"
    REST="${RECORD#*$'\x1f'}"
    C_SUBJECT=$(printf '%s' "${REST%%$'\x1f'*}" | html_escape)
    C_BODY=$(printf '%s' "${REST#*$'\x1f'}" | head -c 400 | html_escape | sed -e 's/[[:space:]]*$//')

    COMMIT_LINES="${COMMIT_LINES}• <b>${C_SUBJECT}</b> (<code>${C_HASH}</code>)
"
    if [ "$TOTAL_COMMITS" -le 3 ] && [ -n "$(printf '%s' "$C_BODY" | tr -d '[:space:]')" ]; then
        COMMIT_LINES="${COMMIT_LINES}<i>${C_BODY}</i>
"
    fi
done < <(git -C "$SCRIPT_DIR" log "$LOCAL_HASH".."$REMOTE_HASH" --format='%h%x1f%s%x1f%b%x1e' 2>/dev/null)

# Append overflow note if there are more than 10 commits
EXTRA_NOTE=""
if [ "$TOTAL_COMMITS" -gt 10 ]; then
    REMAINING=$((TOTAL_COMMITS - 10))
    EXTRA_NOTE="  <i>...and ${REMAINING} more commit(s)</i>
"
fi

# Version transition line
if [ "$CURRENT_VERSION" != "$NEW_VERSION" ]; then
    VERSION_LINE="📦 <b>v${CURRENT_VERSION}  →  v${NEW_VERSION}</b>"
else
    VERSION_LINE="📦 <b>v${NEW_VERSION}</b>"
fi

# Singular/plural
[ "$TOTAL_COMMITS" -eq 1 ] && COMMIT_WORD="commit" || COMMIT_WORD="commits"

send_telegram "✅ <b>Bot Updated Successfully</b>

${VERSION_LINE}

🧾 <b>${TOTAL_COMMITS} ${COMMIT_WORD} applied:</b>
${COMMIT_LINES}${EXTRA_NOTE}
⏱ Changes take effect on the bot's next scheduled run."
log "Update notification sent (v${CURRENT_VERSION} -> v${NEW_VERSION}, ${TOTAL_COMMITS} commits)."
say "Update applied: v${CURRENT_VERSION} -> v${NEW_VERSION} (${TOTAL_COMMITS} ${COMMIT_WORD})."
say "Changes take effect on the bot's next scheduled run."

if [ -n "$ADDED_VARS" ]; then
    send_telegram "⚙️ <b>New Configuration Options</b>

The latest update added new settings to config.py.
They are active with their default values — no action needed unless you want to customize them.

${ADDED_VARS}

To change them, edit config.py on your server."
    log "New variables notification sent."
fi

log "Update completed successfully."
return 0

}

# Run main — the function is fully parsed before execution begins
main "$@"
exit $?
