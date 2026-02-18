# NerdMiners_Public_Pool_Stats Bot
---
- 🇺🇸 [English](https://github.com/function0xMarki/NerdMiners_Public_Pool_Stats/blob/main/README.md) | 🇪🇸 [Español](https://github.com/function0xMarki/NerdMiners_Public_Pool_Stats/blob/main/README_ES.md)
---

Telegram bot that monitors your Bitcoin NerdMiners on [public-pool.io](https://web.public-pool.io) and sends statistics and smart alerts to a Telegram group.

## Features

- **Miner monitoring**: Hashrate *(instant + 24h average)*, best difficulty *(session + all-time)*, uptime, online/offline status
- **Pool statistics**: Total hashrate, miner count, your contribution percentage
- **Bitcoin network stats**: Current block height, difficulty, network hashrate
- **Smart alerts**: Disconnection detected, low hashrate *(vs 24h average)*, new personal records, new/disappeared miners, pool block found
- **Hall of Fame**: Tracks the top 10 best difficulties ever achieved across all sessions
- **Auto-pinned stats message**: A single stats message is kept pinned and updated in the group; pin notification messages are automatically deleted to keep the chat clean
- **Worker identification**: Automatically handles multiple miners with the same API name *(e.g., old NerdMiners that all report as "worker" without customization options)*
- **SQLite storage**: Efficient 90-day rolling history for hashrate averaging and session tracking *(WAL mode for reliability)*
- **Automatic backups**: Database backups every 24 hours with 30-day retention

## Prerequisites

- Python 3.10 or higher
- pip *(Python package manager)*
- A Telegram account
- A Bitcoin address mining on [public-pool.io](https://public-pool.io)

## Telegram Bot Setup

Follow these steps carefully to create and configure your Telegram bot.

### 1. Create the Bot

1. Open Telegram and search for **@BotFather**
2. Send the command `/newbot`
3. Choose a **name** for your bot *(e.g., "NerdMiners Monitor")*
4. Choose a **username** for your bot *(must end in `bot`, e.g., `my_nerdminers_bot`)*
5. BotFather will give you a **Bot Token** — save it, you'll need it later
> **Official documentation**: [Telegram Bot API - BotFather](https://core.telegram.org/bots#botfather)

### 2. Create a Telegram Group

1. Open Telegram and create a **new group**
2. Give it a name *(e.g., "NerdMiners Monitoring")*
3. Telegram requires you to add at least one member *(you can remove them later)*

### 3. Add the Bot to the Group

1. Open the group settings
2. Select **Add Members**
3. Search for your bot by its username
4. Add the bot to the group
5. Go to group settings → **Administrators** → **Add Administrator**
6. Select your bot and enable **at least** these permissions:
   - **Send Messages**
   - **Delete Messages** ← Required for deleting old stats messages and pin notification cleanup
   - **Pin Messages** ← Required for the bot to keep the stats message pinned at the top of the group

### 4. Get the CHAT_ID

The bot needs the group's Chat ID to know where to send messages.

**Method 1 — Using message link** (recommended):

1. Send any message in the group *(e.g., "hello")*
2. Right-click the message and select "Copy Message Link"
3. Paste the URL, which will have a structure similar to this:
   - `https://t.me/c/3892682082/1`
4. Your group ID will be the first group of numbers, and you must add `-100` to it
   - According to this example: `-100` + `3892682082` = `-1003892682082`

### 5. Disable "Allow Groups" in BotFather

This is an important security step. After adding the bot to your group:

1. Open **@BotFather** again
2. Send `/mybots`
3. Select your bot
4. Go to **Bot Settings** → **Allow Groups?**
5. Select **Disable**

This prevents anyone else from adding your bot to other groups. The bot will continue to work in groups where it's already a member.

> **Important**: The bot ignores all direct messages. It only operates in the configured Telegram group.

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd NerdMiners_Public_Pool_Stats
```

### 2. Configure the Bot

Run the setup script:

```bash
chmod +x First_Setup.sh
./First_Setup.sh
```

The script will create `.env` from the `.env.example` template on first run.

```bash
nano .env
```

Set all three variables:

```
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
CHAT_ID=-1001234567890
BTC_ADDRESS=bc1q...
```

Then run the setup script again.
The configuration script will verify that all variables are set and will begin the bot environment setup process, automatically installing the necessary dependencies.
If you're missing any program like Python or pip, it will notify you and show you the command to install it.

```bash
./First_Setup.sh
```

### 3. Customize Worker Names *(Optional)*

Edit `config.py` to set custom display names for your miners.
This way you can assign a more descriptive name to your miner related to the worker name that appears in Public-Pool.
Keep in mind that you should assign a different name to each worker in its configuration.

```python
NAME_SUBSTITUTIONS = {
    "nerdoctaxe": "BitAxe Ultra",
    "worker": "NerdMiner v2",
}
```

### 4. Set Up Cron Job

The bot is designed to run periodically via cron — it is **not** a continuously running service.
Each execution fetches the latest data, updates the pinned stats message, sends any alerts, and exits.

At the end of the `First_Setup.sh` configuration script, you will be shown a command that you must execute to create the cron entry in the system's crontab.

> **Important — Execution frequency**:
> - **Maximum recommended frequency: every 30 minutes** (`*/30 * * * *`).
> - Running more frequently *(e.g., every 5 or 10 minutes)* is **not recommended** because the public-pool.io API may apply **rate limits** that could temporarily block your requests.
> - Running less frequently *(e.g., every hour)* is perfectly fine and will still provide useful monitoring.

## Configuration

All sensitive values are in `.env`:

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram Bot Token from @BotFather |
| `CHAT_ID` | Telegram group Chat ID (negative number) |
| `BTC_ADDRESS` | Your Bitcoin mining address on public-pool.io |

Tunable settings are in `config.py`:

| Setting | Description | Default |
|---------|-------------|---------|
| `API_BASE_URL` | public-pool.io API base URL | `https://public-pool.io:40557/api` |
| `OFFLINE_TIMEOUT_MINUTES` | Minutes of inactivity before a miner is considered offline | `5` |
| `HASHRATE_DROP_PERCENT` | Hashrate drop vs 24h average to trigger alert | `30` |
| `MESSAGE_EDIT_LIMIT_HOURS` | Hours before the stats message is recreated *(see note below)* | `45` |
| `DATA_RETENTION_DAYS` | Days to keep hashrate history in the database | `90` |
| `BACKUP_RETENTION_DAYS` | Days to keep database backups | `30` |
| `NAME_SUBSTITUTIONS` | Custom display names for miners | `{}` |
| `LOG_LEVEL` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `WARNING` |

### ABOUT `MESSAGE_EDIT_LIMIT_HOURS`
*The bot keeps a single pinned message in Telegram that it edits on each run.*
*When the message reaches the age of `MESSAGE_EDIT_LIMIT_HOURS`, the bot deletes it and sends a new one (which is then pinned automatically).*

> **Important**: Telegram imposes a **48-hour limit** for bots — messages older than 48 hours **cannot be edited or deleted** via the Bot API. The default value of **45 hours** provides a safe 3-hour margin. **Do not set this value above 45**, or the bot may be unable to delete the old message, resulting in duplicate pinned messages in the group.

### Worker Name Substitutions

Customize how miner names appear in Telegram messages:

```python
NAME_SUBSTITUTIONS = {
    "nerdoctaxe_1": "NerdMiner Octaxe Gamma Home",
    "nerdoctaxe_2": "NerdMiner Octaxe Gamma Work",
    "worker": "NerdMiner v2 Living Room",
    "worker_2": "NerdMiner v2 Office",
}
```
*For old NerdMiners that all report as `worker` in the API, the bot assigns incremental IDs (`worker_1`, `worker_2`, ...). Run the bot once and check the log to discover assigned IDs.*

## Alerts

| Alert | Trigger |
|-------|---------|
| DISCONNECTION DETECTED | Miner's session ID changed *(new `startTime`)*. Includes previous session duration, estimated downtime, and reconnection time |
| MINER OFFLINE | No activity for more than `OFFLINE_TIMEOUT_MINUTES` minutes |
| LOW HASHRATE | Current hashrate dropped more than `HASHRATE_DROP_PERCENT`% below the 24-hour average |
| NEW PERSONAL RECORD | Miner achieved a new session best difficulty *"BD"* *(also marks all-time records)* |
| NEW MINER DETECTED | A previously unknown miner appeared |
| MINER DISAPPEARED | A known miner is no longer visible in the pool |
| YOUR MINER FOUND A BLOCK | One of YOUR miners found a Bitcoin block *(matched by your BTC_ADDRESS)* |
| BLOCK FOUND BY THE POOL | Another miner on public-pool.io found a Bitcoin block |

## How It Works

1. **Database init**: Creates SQLite tables if they don't exist
2. **Backup**: Creates a timestamped copy of the database *(skipped if one less than 24h old exists)*
3. **Fetch data**: Queries the public-pool.io API for your miners, pool stats, and network stats
4. **Identify workers**: Maps API workers to stable internal IDs *(handles duplicate names)*
5. **Check alerts**: Compares current state against saved state, detects changes, records sessions
6. **Send alerts**: Any triggered alerts are sent as individual messages to the group
7. **Update stats**: Builds the stats message, edits the existing pinned message *(or creates a new one if too old)*
8. **Purge**: Deletes hashrate samples older than `DATA_RETENTION_DAYS`

## Project Structure

```
NerdMiners_Public_Pool_Stats/
├── .env                        # Secrets: BOT_TOKEN, CHAT_ID, BTC_ADDRESS (not in git)
├── .env.example                # Template for .env
├── config.py                   # Tunable bot settings and worker name substitutions
├── database.py                 # SQLite persistence layer (WAL mode, foreign keys)
├── NerdMiners_Bot.py           # Main bot script (entry point)
├── First_Setup.sh              # First-time setup script
├── requirements.txt            # Python dependencies
├── DB.db                       # SQLite database (auto-generated)
├── Logs/                       # Log files directory (auto-generated)
│   └── NerdMiners_Public_Pool_Stats_Bot.log
└── Backup/                     # Database backups (auto-generated, 30-day retention)
    └── NerdMiners_Public_Pool_Stats_DDMMYYYY_HHMMSS.db
```

## API Endpoints

Base URL: `https://public-pool.io:40557/api`

| Endpoint | Description |
|----------|-------------|
| `/api/client/{address}` | Workers for a Bitcoin address (hashrate, best diff, sessions) |
| `/api/pool` | Pool-wide statistics (total hashrate, miners, blocks found) |
| `/api/network` | Bitcoin network statistics (block height, difficulty, hashrate) |

## License

[MIT](https://github.com/function0xMarki/NerdMiners_Public_Pool_Stats/blob/main/LICENSE)
