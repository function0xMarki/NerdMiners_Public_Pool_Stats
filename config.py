"""
NerdMiners_Public_Pool_Stats Bot Configuration.
Edit these values according to your setup.

Note: BOT_TOKEN, CHAT_ID, and BTC_ADDRESS are stored in the .env file,
not here. See .env.example for the template.
"""

# ===========================================================================
# AUTO-UPDATE
# ===========================================================================

# Enable or disable automatic updates from the GitHub repository.
# True (default): the bot checks for updates on every run and applies them automatically.
# False:          disables all automatic updates; you must update manually via git.
AUTO_UPDATE = True

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

# Number of consecutive runs that must show a hashrate drop before alerting.
# With a 30-minute cron, 2 strikes means the drop must persist at least 30 minutes.
# Increase to require a longer sustained drop before alerting (e.g., 3 = ~60 min).
HASHRATE_ALERT_STRIKES = 2

# Hours before resending a LOW HASHRATE alert for the same miner.
# The cooldown resets automatically when the miner's hashrate recovers.
HASHRATE_ALERT_COOLDOWN_HOURS = 4

# Whether to notify on every new session best difficulty record.
# False (default): only alert when a miner beats their all-time best difficulty.
# True:            alert on any new session best, even if it doesn't beat the all-time record.
NOTIFY_SESSION_BD_RECORD = False

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
# NAME_SUBSTITUTIONS = '{"nerdoctaxe": "NerdMiner Octaxe Gamma", "worker": "NerdMiner v2"}'
#
# If a name is not in this dictionary, the original API name is displayed.
NAME_SUBSTITUTIONS = '{"nerdoctaxe": "NerdMiner Octaxe Gamma", "worker": "NerdMiner v2"}'

# ===========================================================================
# LOGGING
# ===========================================================================

# Log level for the bot. Valid values: "DEBUG", "INFO", "WARNING", "ERROR".
# - DEBUG:   Everything, very verbose (useful for troubleshooting)
# - INFO:    Normal operations + warnings + errors
# - WARNING: Only important events and errors (default, recommended)
# - ERROR:   Only errors
LOG_LEVEL = "WARNING"
