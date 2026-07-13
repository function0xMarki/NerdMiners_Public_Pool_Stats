#!/bin/bash
# =============================================================================
# NerdMiners_Public_Pool_Stats Bot - Install & Self-Heal
#
# Usage:
#   ./install.sh                Interactive first-time setup. Also works as a
#                               manual repair tool (e.g. if the venv is broken
#                               and the bot cannot start).
#   ./install.sh --heal         Quiet self-heal mode. Called automatically by
#                               NerdMiners_Bot.py on every run and by update.sh
#                               after applying an update. Creates missing
#                               directories, repairs a broken venv, installs
#                               missing dependencies and fixes permissions.
#   ./install.sh --force-venv   Interactive setup, rebuilding the venv from
#                               scratch even if it looks healthy.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOGS_DIR="$SCRIPT_DIR/Logs"
LOG_FILE="$LOGS_DIR/NerdMiners_Public_Pool_Stats_Bot.log"

MODE="interactive"
FORCE_VENV=false
case "$1" in
    --heal) MODE="heal" ;;
    --force-venv) FORCE_VENV=true ;;
esac

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - INSTALL - $1" >> "$LOG_FILE"
}

# Print to stdout only in interactive mode
say() {
    if [ "$MODE" = "interactive" ]; then
        echo -e "$1"
    fi
}

# Portable SHA-256 of a file (sha256sum on Linux, shasum on macOS)
hash_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | cut -d' ' -f1
    else
        cksum "$1" | cut -d' ' -f1
    fi
}

# ---------------------------------------------------------------------------
# Self-heal core: directories, venv, dependencies, permissions.
# Quiet and fast when everything is healthy; only logs when it repairs.
# Returns 0 on success, 1 on a fatal problem (e.g. python3 missing).
# ---------------------------------------------------------------------------
heal_environment() {
    local HEALED=false

    # --- Directories ---
    if [ ! -d "$LOGS_DIR" ] || [ ! -d "$SCRIPT_DIR/Backup" ]; then
        mkdir -p "$LOGS_DIR" "$SCRIPT_DIR/Backup"
        HEALED=true
        log "Created missing Logs/Backup directories"
    fi

    # --- Virtual environment ---
    if [ "$FORCE_VENV" = true ] && [ -d "$SCRIPT_DIR/venv" ]; then
        say "  ${YELLOW}!${NC} Rebuilding virtual environment (--force-venv)..."
        rm -rf "$SCRIPT_DIR/venv"
    fi

    if ! "$SCRIPT_DIR/venv/bin/python" -c "import sys" >/dev/null 2>&1; then
        if ! command -v python3 >/dev/null 2>&1; then
            log "FATAL: python3 is not installed; cannot create venv"
            say "  ${RED}ERROR:${NC} python3 is not installed."
            return 1
        fi
        log "venv missing or broken - recreating"
        say "  ${YELLOW}!${NC} Creating virtual environment..."
        rm -rf "$SCRIPT_DIR/venv"
        if ! python3 -m venv "$SCRIPT_DIR/venv" >> "$LOG_FILE" 2>&1; then
            log "FATAL: could not create venv"
            say "  ${RED}ERROR:${NC} could not create the virtual environment."
            return 1
        fi
        "$SCRIPT_DIR/venv/bin/pip" install --upgrade pip --quiet >> "$LOG_FILE" 2>&1
        rm -f "$SCRIPT_DIR/venv/.requirements.hash"
        HEALED=true
    fi

    # --- Dependencies (hash stamp + import check) ---
    local REQ_HASH STAMP NEED_DEPS=false
    REQ_HASH=$(hash_file "$SCRIPT_DIR/requirements.txt")
    STAMP=$(cat "$SCRIPT_DIR/venv/.requirements.hash" 2>/dev/null)
    if [ "$REQ_HASH" != "$STAMP" ]; then
        NEED_DEPS=true
        log "requirements.txt changed or never installed - installing dependencies"
    elif ! "$SCRIPT_DIR/venv/bin/python" -c "import requests, dotenv" >/dev/null 2>&1; then
        NEED_DEPS=true
        log "dependencies broken despite valid stamp - reinstalling"
    fi

    if [ "$NEED_DEPS" = true ]; then
        say "  Installing dependencies..."
        if "$SCRIPT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" --quiet >> "$LOG_FILE" 2>&1; then
            echo "$REQ_HASH" > "$SCRIPT_DIR/venv/.requirements.hash"
            log "Dependencies installed successfully"
            HEALED=true
        else
            log "ERROR: pip install failed"
            say "  ${RED}ERROR:${NC} pip install failed. See $LOG_FILE"
            return 1
        fi
    fi

    # --- Permissions (idempotent; secrets and data owner-only) ---
    chmod 700 "$SCRIPT_DIR"/*.sh 2>/dev/null
    chmod 600 "$SCRIPT_DIR/.env" 2>/dev/null
    chmod 600 "$SCRIPT_DIR"/DB.db* 2>/dev/null
    chmod 700 "$LOGS_DIR" "$SCRIPT_DIR/Backup" 2>/dev/null
    chmod 600 "$SCRIPT_DIR/Backup"/*.db 2>/dev/null
    chmod 600 "$LOGS_DIR"/*.log* 2>/dev/null

    if [ "$HEALED" = true ]; then
        log "Self-heal completed (repairs were applied)"
    fi
    return 0
}

# ---------------------------------------------------------------------------
# --heal mode: run the self-heal quietly and exit
# ---------------------------------------------------------------------------
if [ "$MODE" = "heal" ]; then
    mkdir -p "$LOGS_DIR"
    heal_environment
    exit $?
fi

# ---------------------------------------------------------------------------
# Interactive setup
# ---------------------------------------------------------------------------
set -e
mkdir -p "$LOGS_DIR"

echo ""
echo -e "${CYAN}==========================================================${NC}"
echo -e "       NerdMiners_Public_Pool_Stats Bot - Setup & Repair         "
echo -e "${CYAN}==========================================================${NC}"
echo ""

# -------------------------------------------------------------------------
# Step 1: Create .env from template if it doesn't exist
# -------------------------------------------------------------------------
echo -e "${YELLOW}[1/5]${NC} Checking .env file..."

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        chmod 600 .env
        echo -e "  ${GREEN}✓${NC} Created .env from .env.example template"
        echo ""
        echo -e "  ${YELLOW}ACTION REQUIRED:${NC} Edit the .env file and fill in your values:"
        echo ""
        echo "  You need to set:"
        echo "    - BOT_TOKEN  (get from @BotFather on Telegram)"
        echo "    - CHAT_ID    (your Telegram group ID, see README.md)"
        echo "    - BTC_ADDRESS (your Bitcoin mining address on public-pool.io)"
        echo ""
        echo "  Then run this script again."
        echo ""
        exit 1
    else
        echo -e "${RED}ERROR:${NC} .env.example template not found."
        echo ""
        echo "  Create a .env file with the following content:"
        echo ""
        echo "    BOT_TOKEN="
        echo "    CHAT_ID="
        echo "    BTC_ADDRESS="
        echo ""
        exit 1
    fi
fi

echo -e "  ${GREEN}✓${NC} .env file exists"

# -------------------------------------------------------------------------
# Step 2: Verify .env variables are configured
# -------------------------------------------------------------------------
echo -e "${YELLOW}[2/5]${NC} Verifying .env configuration..."

# Check BOT_TOKEN
BOT_TOKEN_VALUE=$(grep -E "^BOT_TOKEN=" .env | cut -d'=' -f2- | tr -d '[:space:]')
if [ -z "$BOT_TOKEN_VALUE" ]; then
    echo -e "  ${RED}ERROR:${NC} BOT_TOKEN is not configured in .env"
    echo ""
    echo "  Edit the .env file and set your Telegram Bot Token:"
    echo "    nano $SCRIPT_DIR/.env"
    echo ""
    echo "  Get your token from @BotFather on Telegram."
    echo "  See README.md for detailed instructions."
    echo ""
    exit 1
fi
echo -e "  ${GREEN}✓${NC} BOT_TOKEN is set"

# Check CHAT_ID
CHAT_ID_VALUE=$(grep -E "^CHAT_ID=" .env | cut -d'=' -f2- | tr -d '[:space:]')
if [ -z "$CHAT_ID_VALUE" ]; then
    echo -e "  ${RED}ERROR:${NC} CHAT_ID is not configured in .env"
    echo ""
    echo "  Edit the .env file and set your Telegram group Chat ID:"
    echo "    nano $SCRIPT_DIR/.env"
    echo ""
    echo "  See README.md for instructions on how to obtain the CHAT_ID."
    echo ""
    exit 1
fi
echo -e "  ${GREEN}✓${NC} CHAT_ID is set"

# Check BTC_ADDRESS
BTC_ADDRESS_VALUE=$(grep -E "^BTC_ADDRESS=" .env | cut -d'=' -f2- | tr -d '[:space:]')
if [ -z "$BTC_ADDRESS_VALUE" ]; then
    echo -e "  ${RED}ERROR:${NC} BTC_ADDRESS is not configured in .env"
    echo ""
    echo "  Edit the .env file and set your Bitcoin mining address:"
    echo "    nano $SCRIPT_DIR/.env"
    echo ""
    exit 1
fi
echo -e "  ${GREEN}✓${NC} BTC_ADDRESS is set"

# -------------------------------------------------------------------------
# Step 3: Check Python 3
# -------------------------------------------------------------------------
echo -e "${YELLOW}[3/5]${NC} Checking Python 3..."

if ! command -v python3 &>/dev/null; then
    echo -e "  ${RED}ERROR:${NC} python3 is not installed."
    echo ""
    echo "  Install Python 3 with:"
    echo ""
    echo "    sudo apt update && sudo apt install python3 python3-pip python3-venv"
    echo ""
    echo "  Or on other distributions:"
    echo "    Fedora/RHEL: sudo dnf install python3 python3-pip"
    echo "    Arch:        sudo pacman -S python python-pip"
    echo "    macOS:       brew install python3"
    echo ""
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1)
echo -e "  ${GREEN}✓${NC} $PYTHON_VERSION found"

# -------------------------------------------------------------------------
# Step 4: Check pip / venv support
# -------------------------------------------------------------------------
echo -e "${YELLOW}[4/5]${NC} Checking pip and venv..."

if ! python3 -m pip --version &>/dev/null; then
    echo -e "  ${RED}ERROR:${NC} pip is not installed for Python 3."
    echo ""
    echo "  Install pip with:"
    echo ""
    echo "    sudo apt update && sudo apt install python3-pip python3-venv"
    echo ""
    echo "  Or on other distributions:"
    echo "    Fedora/RHEL: sudo dnf install python3-pip"
    echo "    Arch:        sudo pacman -S python-pip"
    echo "    macOS:       python3 -m ensurepip --upgrade"
    echo ""
    exit 1
fi

if ! python3 -c "import venv" &>/dev/null; then
    echo -e "  ${RED}ERROR:${NC} Python venv module is not available."
    echo ""
    echo "  Install it with:"
    echo ""
    echo "    sudo apt update && sudo apt install python3-venv"
    echo ""
    exit 1
fi

echo -e "  ${GREEN}✓${NC} pip and venv are available"

# -------------------------------------------------------------------------
# Step 5: Virtual environment, dependencies and permissions (self-heal)
# -------------------------------------------------------------------------
echo -e "${YELLOW}[5/5]${NC} Setting up environment (venv, dependencies, permissions)..."

set +e
heal_environment
HEAL_RESULT=$?
set -e
if [ $HEAL_RESULT -ne 0 ]; then
    echo -e "  ${RED}ERROR:${NC} environment setup failed. See $LOG_FILE"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Virtual environment ready"
echo -e "  ${GREEN}✓${NC} Dependencies installed"
echo -e "  ${GREEN}✓${NC} File permissions secured (.env/DB 600, scripts 700)"

# -------------------------------------------------------------------------
# Done
# -------------------------------------------------------------------------
echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}   Setup completed successfully!         ${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "  To run the bot manually:"
echo "  $SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/NerdMiners_Bot.py"
echo ""

CRON_COMMENT="# NerdMiners_Public_Pool_Stats_Bot"
CRON_JOB="*/30 * * * * $SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/NerdMiners_Bot.py"

# Check if cron job already exists (as a real entry, not a commented-out line)
if crontab -l 2>/dev/null | grep -v '^[[:space:]]*#' | grep -qF "$SCRIPT_DIR/NerdMiners_Bot.py"; then
    echo -e "  ${GREEN}✓${NC} Cron job already configured."
    echo ""
else
    echo -e "  ${YELLOW}NEXT STEP:${NC} Set up automatic execution every 30 minutes."
    echo -e "  > Copy and paste ${RED}the next FULL GREEN COMMAND${NC} to add the cron job automatically:"
    echo -e "    ${GREEN}(crontab -l 2>/dev/null; echo \"$CRON_COMMENT\"; echo \"$CRON_JOB\") | crontab -${NC}"
    echo ""
    echo -e "> Use ${GREEN}crontab -l${NC} to verify the cron job was added successfully."
    echo ""
fi

echo "> See README.md for more details."
echo ""
