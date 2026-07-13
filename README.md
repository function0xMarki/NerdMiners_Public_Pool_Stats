# NerdMiners_Public_Pool_Stats Bot
---
- 🇺🇸 [English](https://github.com/function0xMarki/NerdMiners_Public_Pool_Stats/blob/main/README.md) | 🇪🇸 [Español](https://github.com/function0xMarki/NerdMiners_Public_Pool_Stats/blob/main/README_ES.md)
---

Telegram bot that monitors your Bitcoin NerdMiners on Public-Pool and sends statistics and smart alerts to a Telegram group.

<div align="center">
  
![Version](https://img.shields.io/badge/Version-1.1.0-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![pip](https://img.shields.io/badge/Python-pip-green.svg)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

## Features

- **Miner monitoring**: Hashrate *(instant + 24h average)*, best difficulty *(session + all-time)*, uptime, online/offline status
- **Pool statistics**: Total hashrate, miner count, your contribution percentage
- **Bitcoin network stats**: Current block height, difficulty, network hashrate
- **Smart alerts**: Disconnection detected, low hashrate *(vs 24h average)*, new personal records, new/disappeared miners, pool block found
- **TOP BD**: Tracks the top 10 best difficulties ever achieved across all sessions, displaying the top 5 by default in the stats message
- **Auto-pinned stats message**: A single stats message is kept pinned and updated in the group; pin notification messages are automatically deleted to keep the chat clean
- **Worker identification**: Automatically handles multiple miners with the same API name *(e.g., old NerdMiners that all report as "worker" without customization options)*
- **SQLite storage**: Efficient 90-day rolling history for hashrate averaging and session tracking *(WAL mode for reliability)*
- **Automatic backups**: Database backups every 24 hours with 30-day retention
- **Manual updates via Telegram**: The bot announces new versions in the group; the group owner/admin applies them with the `/update` command *(or by running `update.sh` on the server)*
- **Self-healing environment**: On every run the bot verifies and repairs its own environment *(missing directories, broken venv, missing dependencies, insecure file permissions)*

<p align="center">
  <img width="251" height="460" alt="demo" src="https://github.com/user-attachments/assets/0e418066-41a3-420a-9a9b-d088cfc043d8" />
</p>

## Prerequisites

- Python 3.10 or higher
- pip *(Python package manager)*
- A Telegram account
- A Bitcoin address mining on [public-pool.io](https://public-pool.io) or auto-hosted Public-Pool

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
chmod +x install.sh
./install.sh
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
The script will verify that all variables are set and will set up the bot environment, automatically installing the necessary dependencies and securing file permissions.
If you're missing any program like Python or pip, it will notify you and show you the command to install it.

```bash
./install.sh
```

> `install.sh` is also the repair tool: the bot runs `install.sh --heal` automatically on every start to fix anything broken *(missing directories, damaged venv, missing dependencies, wrong permissions)*. If the bot ever stops running because the venv was deleted or corrupted, just run `./install.sh` manually once.

### 3. Customize Worker Names *(Optional)*

Edit `config.py` to configure custom names for your miners and how they will be displayed in Telegram messages.
This way you can assign a more descriptive name to your miner related to the worker name that appears in Public-Pool.
Keep in mind that you should assign a different name to each worker in its configuration.

```python
NAME_SUBSTITUTIONS = '{"nerdoctaxe_1": "NerdMiner Octaxe Gamma Home", "nerdoctaxe_2": "NerdMiner Octaxe Gamma Work", "worker": "NerdMiner v2 Living Room", "worker_2": "NerdMiner v2 Office"}'
```
> **Important**: The value must be a **single-line JSON string** — do not split it across lines. This format allows the update system to preserve your names during upgrades.
*For old NerdMiners that all report as `worker` in the API, the bot assigns incremental IDs (`worker_1`, `worker_2`, ...). Run the bot once and check the log to discover assigned IDs.*

### 4. Set Up Cron Job

The bot is designed to run periodically via cron — it is **not** a continuously running service.
Each execution repairs its environment if needed, fetches the latest data, updates the pinned stats message, sends any alerts, and exits.

At the end of the `install.sh` setup script, you will be shown a command that you must execute to create the cron entry in the system's crontab.

> **Important — Execution frequency**:
> - **Recommended frequency: every 30 minutes** (`*/30 * * * *`).
> - Running more frequently *(e.g., every 5 or 10 minutes)* is **not recommended when using public-pool.io**, as its API may apply **rate limits** that could temporarily block your requests.
> - If you are using a **self-hosted public-pool instance**, there are no rate limits — you may run the bot as frequently as you like.
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
| `UPDATE_MODE` | `"manual"`: the bot announces new versions in Telegram and you apply them with `/update` or `update.sh` *(see [Updates](#updates))*. `"auto"`: updates are applied automatically on every run *(legacy behavior)* | `"manual"` |
| `API_BASE_URL` | API base URL. Pre-configured for **public-pool.io**. Self-hosted instances use a different URL and port *(e.g., `http://umbrel.local:3334/api`)*. See [Self-hosted public-pool](#self-hosted-public-pool) below | `https://public-pool.io:40557/api` |
| `OFFLINE_TIMEOUT_MINUTES` | Minutes of inactivity before a miner is considered offline | `5` |
| `HASHRATE_DROP_PERCENT` | Hashrate drop vs 24h average to trigger alert | `30` |
| `HASHRATE_ALERT_STRIKES` | Consecutive runs with a hashrate drop required before alerting. With a 30-min cron, `2` = drop must persist ≥30 min | `2` |
| `HASHRATE_ALERT_COOLDOWN_HOURS` | Hours before resending a LOW HASHRATE alert for the same miner. Resets automatically when hashrate recovers | `4` |
| `NOTIFY_SESSION_BD_RECORD` | `False`: alert only when a miner beats their **all-time** best difficulty. `True`: alert on every new session best, even if it doesn't beat the all-time record | `False` |
| `SHOW_TOP_BD` | Top BDs shown on Telegram | `5` |
| `MESSAGE_EDIT_LIMIT_HOURS` | Hours before the stats message is recreated *(see note below)* | `45` |
| `DATA_RETENTION_DAYS` | Days to keep hashrate history in the database | `90` |
| `BACKUP_RETENTION_DAYS` | Days to keep database backups | `30` |
| `NAME_SUBSTITUTIONS` | Custom display names for miners *(single-line JSON string)* | `'{}'` |
| `LOG_LEVEL` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `WARNING` |

### ABOUT `MESSAGE_EDIT_LIMIT_HOURS`
*The bot keeps a single pinned message in Telegram that it edits on each run.*
*When the message reaches the age of `MESSAGE_EDIT_LIMIT_HOURS`, the bot deletes it and sends a new one (which is then pinned automatically).*

> **Important**: Telegram imposes a **48-hour limit** for bots — messages older than 48 hours **cannot be edited or deleted** via the Bot API. The default value of **45 hours** provides a safe 3-hour margin. **Do not set this value above 45**, or the bot may be unable to delete the old message, resulting in duplicate pinned messages in the group.

## Alerts

| Alert | Trigger |
|-------|---------|
| DISCONNECTION DETECTED | Miner's session ID changed *(new `startTime`)*. Includes previous session duration, estimated downtime, and reconnection time |
| MINER OFFLINE | No activity for more than `OFFLINE_TIMEOUT_MINUTES` minutes |
| LOW HASHRATE | Hashrate dropped more than `HASHRATE_DROP_PERCENT`% below the 24h average for `HASHRATE_ALERT_STRIKES` consecutive runs. Cooldown of `HASHRATE_ALERT_COOLDOWN_HOURS`h between alerts; resets on recovery |
| NEW PERSONAL RECORD | Miner beat their **all-time** best difficulty *(default)*. Set `NOTIFY_SESSION_BD_RECORD = True` to also alert on session bests that don't beat the all-time record |
| NEW MINER DETECTED | A previously unknown miner appeared |
| MINER DISAPPEARED | A known miner is no longer visible in the pool. After 2 alerts, tracking is paused *(history and records are preserved)* |
| MINER BACK ONLINE | A paused miner reappeared in the pool. Tracking resumes automatically with all its history intact |
| YOUR MINER FOUND A BLOCK | One of YOUR miners found a Bitcoin block *(matched by your BTC_ADDRESS)* |
| BLOCK FOUND BY THE POOL | Another miner on public-pool.io found a Bitcoin block |

## Updates

Updates are **manual by default** — you stay in control of when new code goes live:

1. On every run, the bot checks the GitHub repository. When a new version is available, it sends a single notification to the group *(once per version, no spam)* with the version transition, the list of new commits, and how to apply it.
2. To apply the update, choose whichever you prefer:
   - **From Telegram**: send `/update` in the group. Only the **group owner or an administrator** can use this command; anyone else is politely refused. Since the bot runs on a schedule, the command **stays queued** and is executed on the bot's next scheduled start *(within ~30 min with the recommended cron)*. Sending `/update` several times queues just **one** update.
   - **From the server**: run `./update.sh` in the bot directory for immediate effect.
3. Once applied, the bot confirms in the group with a nicely formatted message: version transition *(e.g., `v1.1.0 → v1.2.0`)*, and each commit with its description. The new code takes effect on the bot's next scheduled run.

The update always preserves your `.env`, your `config.py` values, the database, logs, and backups. If the update adds new configuration options, the bot tells you about them and they start with safe defaults.

Any other message or command sent to the group is ignored by the bot — `/update` is the only command it listens to.

> Prefer the old fully automatic behavior? Set `UPDATE_MODE = "auto"` in `config.py` and updates will be applied on every run without asking.

## How It Works

1. **Self-heal**: Runs `install.sh --heal` to verify and repair the environment *(directories, venv, dependencies, permissions)*
2. **Update handling**: Reads queued group commands; applies the update if an authorized `/update` is pending, otherwise announces newly available versions *(once per version)*
3. **Database init**: Creates SQLite tables if they don't exist *(and migrates old schemas)*
4. **Backup**: Creates a timestamped copy of the database *(skipped if one less than 24h old exists)*
5. **Fetch data**: Queries the public-pool.io API for your miners, pool stats, and network stats
6. **Identify workers**: Maps API workers to stable internal IDs *(handles duplicate names)*
7. **Check alerts**: Compares current state against saved state, detects changes, records sessions
8. **Send alerts**: Any triggered alerts are sent as individual messages to the group
9. **Update stats**: Builds the stats message, edits the existing pinned message *(or creates a new one if too old)*
10. **Purge**: Deletes hashrate samples older than `DATA_RETENTION_DAYS`

## Project Structure

```
NerdMiners_Public_Pool_Stats/
├── .env                        # Secrets: BOT_TOKEN, CHAT_ID, BTC_ADDRESS (not in git)
├── .env.example                # Template for .env
├── VERSION                     # Current bot version (single source of truth)
├── config.py                   # Tunable bot settings and worker name substitutions
├── database.py                 # SQLite persistence layer (WAL mode, foreign keys)
├── NerdMiners_Bot.py           # Main bot script (entry point)
├── install.sh                  # Setup script + self-heal (--heal, run on every bot start)
├── update.sh                   # Manual update script (/update command or terminal)
├── requirements.txt            # Python dependencies
├── DB.db                       # SQLite database (auto-generated)
├── Logs/                       # Log files directory (auto-generated)
│   └── NerdMiners_Public_Pool_Stats_Bot.log
└── Backup/                     # Database backups (auto-generated, 30-day retention)
    └── NerdMiners_Public_Pool_Stats_MMDDYYYY_HHMMSS.db
```

## Security & Permissions

- `.env` *(secrets)* and all database files are kept at `600` *(owner read/write only)*; scripts at `700`; `Logs/` and `Backup/` at `700`. The bot re-applies these permissions on every run.
- The `/update` command is restricted to the group owner and administrators.
- Remember to disable **Allow Groups** in @BotFather *(see setup above)* so nobody can add your bot to another group.

## Troubleshooting

- **The bot stopped running and there is nothing in the logs**: the venv may have been deleted or corrupted so cron cannot even start Python. Run `./install.sh` on the server — it rebuilds everything — and wait for the next cron run.
- **An update failed**: the bot sends the failure reason to the group. Your configuration backup is kept at `.config.py.bak`; running `./update.sh` again after fixing the cause is safe.

## API Endpoints

Base URL: `https://public-pool.io:40557/api`

| Endpoint | Description |
|----------|-------------|
| `/api/client/{address}` | Workers for a Bitcoin address (hashrate, best diff, sessions) |
| `/api/pool` | Pool-wide statistics (total hashrate, miners, blocks found) |
| `/api/network` | Bitcoin network statistics (block height, difficulty, hashrate) |

## Self-hosted public-pool

This bot is compatible with **self-hosted public-pool instances**. [public-pool](https://github.com/benjamin-wilson/public-pool) is the open-source software behind public-pool.io — anyone can run their own private instance, including via a one-click install on [Umbrel](https://apps.umbrel.com/app/public-pool).

The bot comes pre-configured for public-pool.io. To use your own instance, change `API_BASE_URL` in `config.py` to point to your server's IP or hostname and its API port:

```python
# Self-hosted example (Umbrel, default port 3334)
API_BASE_URL = "http://umbrel.local:3334/api"
```

The port depends on your installation — check the network settings of your public-pool instance.

## License

[MIT](https://github.com/function0xMarki/NerdMiners_Public_Pool_Stats/blob/main/LICENSE)
