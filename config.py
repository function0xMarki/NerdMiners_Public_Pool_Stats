"""
NerdMiners_Public_Pool_Stats Bot Configuration.
Edit these values according to your setup.

Note: BOT_TOKEN, CHAT_ID, and BTC_ADDRESS are stored in the .env file,
not here. See .env.example for the template.
"""

# ===========================================================================
# API
# ===========================================================================

# public-pool.io API base URL
API_BASE_URL = "https://public-pool.io:40557/api"

# ===========================================================================
# ALERTS
# ===========================================================================

# Minutes without activity before a miner is considered offline
OFFLINE_TIMEOUT_MINUTES = 5

# Hashrate drop percentage (vs 24h average) to trigger a LOW HASHRATE alert
HASHRATE_DROP_PERCENT = 30

# ===========================================================================
# MESSAGE MANAGEMENT
# ===========================================================================

# Maximum hours before the stats message is recreated instead of edited.
# Telegram does not allow editing/deleting messages older than 48h via Bot API.
# We use 45h as a safety margin.
MESSAGE_EDIT_LIMIT_HOURS = 45

# ===========================================================================
# DATA RETENTION
# ===========================================================================

# Number of days to keep hashrate history samples in the database.
# Older samples are automatically purged on each run.
DATA_RETENTION_DAYS = 90

# Number of days to keep database backups.
# Older backups are automatically deleted on each run.
BACKUP_RETENTION_DAYS = 30

# ===========================================================================
# WORKER NAME SUBSTITUTIONS
# ===========================================================================

# Map internal worker IDs to custom display names shown in Telegram messages.
#
# For miners with unique API names (e.g., "nerdoctaxe"), use that name as key.
# For old NerdMiners that all report as "worker" in the API, the bot assigns
# incremental IDs (worker_1, worker_2, ...) which you can map here.
#
# Run the bot once and check the log to discover your workers' internal IDs.
#
# Example:
#   NAME_SUBSTITUTIONS = {
#       "nerdoctaxe": "BitAxe Ultra",
#       "worker_1": "NerdMiner Living Room",
#       "worker_2": "NerdMiner Office",
#   }
#
# If a name is not in this dictionary, the original API name is displayed.
NAME_SUBSTITUTIONS = {}

# ===========================================================================
# LOGGING
# ===========================================================================

# Log level for the bot. Valid values: "DEBUG", "INFO", "WARNING", "ERROR".
# - DEBUG:   Everything, very verbose (useful for troubleshooting)
# - INFO:    Normal operations + warnings + errors
# - WARNING: Only important events and errors (default, recommended)
# - ERROR:   Only errors
LOG_LEVEL = "WARNING"

