#!/bin/bash
# =============================================================================
# NerdMiners_Public_Pool_Stats Bot - First Time Setup
# Run this script after cloning the repository to set up the bot environment.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}==========================================================${NC}"
echo -e "         NerdMiners_Public_Pool_Stats Bot - First Time Setup          "
echo -e "${CYAN}==========================================================${NC}"
echo ""

# -------------------------------------------------------------------------
# Step 1: Create .env from template if it doesn't exist
# -------------------------------------------------------------------------
echo -e "${YELLOW}[1/5]${NC} Checking .env file..."

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
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
# Step 5: Create virtual environment and install dependencies
# -------------------------------------------------------------------------
echo -e "${YELLOW}[5/5]${NC} Setting up virtual environment..."

if [ -d "venv" ]; then
    echo -e "  ${YELLOW}!${NC} Virtual environment already exists. Recreating..."
    rm -rf venv
fi

python3 -m venv venv
echo -e "  ${GREEN}✓${NC} Virtual environment created"

echo "  Installing dependencies..."
venv/bin/pip install --upgrade pip --quiet
venv/bin/pip install -r requirements.txt --quiet
echo -e "  ${GREEN}✓${NC} Dependencies installed"

# Make all shell scripts executable
chmod +x "$SCRIPT_DIR"/*.sh
echo -e "  ${GREEN}✓${NC} Shell scripts set as executable"

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

CRON_LINE="# NerdMiners_Public_Pool_Stats_Bot\n*/30 * * * * $SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/NerdMiners_Bot.py\n"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -qF "$SCRIPT_DIR/NerdMiners_Bot.py"; then
    echo -e "  ${GREEN}✓${NC} Cron job already configured."
    echo ""
else
    echo -e "  ${YELLOW}NEXT STEP:${NC} Set up automatic execution every 30 minutes."
    echo -e "  > Copy and paste ${RED}the next FULL GREEN COMMAND${NC} to add the cron job automatically:"
    echo -e "    ${GREEN}(crontab -l 2>/dev/null; echo \"$CRON_LINE\") | crontab -${NC}"
    echo ""
    echo -e "> Use ${GREEN}crontab -l${NC} to verify the cron job was added successfully."
    echo ""
fi

echo "> See README.md for more details."
echo ""
