#!/usr/bin/env python3
"""
NerdMiners_Public_Pool_Stats Bot Telegram Bot.
Monitors Bitcoin miners on public-pool.io and sends statistics and alerts
to a Telegram group. Designed to run periodically via cron.
"""

import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from html import escape as html_escape
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests
from dotenv import load_dotenv

import database as db
from config import (
    API_BASE_URL,
    BACKUP_RETENTION_DAYS,
    DATA_RETENTION_DAYS,
    HASHRATE_ALERT_COOLDOWN_HOURS,
    HASHRATE_ALERT_STRIKES,
    HASHRATE_DROP_PERCENT,
    LOG_LEVEL,
    MESSAGE_EDIT_LIMIT_HOURS,
    NAME_SUBSTITUTIONS as _RAW_NAME_SUBSTITUTIONS,
    NOTIFY_SESSION_BD_RECORD,
    OFFLINE_TIMEOUT_MINUTES,
    SHOW_TOP_BD,
    UPDATE_MODE,
    UPTIME_WINDOW_DAYS,
)

# Load environment variables
load_dotenv()

# New files (DB, WAL journals, logs, backups) must be readable only by the
# user running the bot: they contain chat IDs, token-bearing URLs (in error
# logs) and mining data.
os.umask(0o077)

# Worker name substitutions (JSON string from config.py)
try:
    NAME_SUBSTITUTIONS: dict[str, str] = json.loads(_RAW_NAME_SUBSTITUTIONS)
except (json.JSONDecodeError, TypeError):
    NAME_SUBSTITUTIONS = {}

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BTC_ADDRESS = os.getenv("BTC_ADDRESS")

# Construct API URLs from .env and config
API_URL = f"{API_BASE_URL}/client/{BTC_ADDRESS}" if BTC_ADDRESS else ""
POOL_API_URL = f"{API_BASE_URL}/pool"
NETWORK_API_URL = f"{API_BASE_URL}/network"

# Paths
SCRIPT_DIR = Path(__file__).parent
LOGS_DIR = SCRIPT_DIR / "Logs"
BACKUP_DIR = SCRIPT_DIR / "Backup"

# Bot version (single source of truth: the VERSION file)
try:
    BOT_VERSION = (SCRIPT_DIR / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
except OSError:
    BOT_VERSION = "unknown"

# Ensure directories exist
LOGS_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

LOG_FILE = LOGS_DIR / "NerdMiners_Public_Pool_Stats_Bot.log"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("NerdMiners")
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.WARNING))

_handler = RotatingFileHandler(
    str(LOG_FILE), maxBytes=1_000_000, backupCount=2, encoding="utf-8"
)
_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
logger.addHandler(_handler)

# Telegram API base URL
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Message edit limit in seconds
MESSAGE_EDIT_LIMIT = MESSAGE_EDIT_LIMIT_HOURS * 3600


# ===========================================================================
# Display helpers
# ===========================================================================

def _safe_float(value, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_str(value, default: str = "") -> str:
    """Return *value* if it is a string, otherwise *default*."""
    return value if isinstance(value, str) else default


def get_display_name(internal_id: str) -> str:
    """Get display name for a worker, applying substitutions from config.

    Returns HTML-escaped name safe for use in Telegram HTML messages.
    """
    name = NAME_SUBSTITUTIONS.get(internal_id, internal_id)
    return html_escape(name)


def format_hashrate(hashrate: float) -> str:
    """Format hashrate into human-readable units."""
    units = ["H/s", "KH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s", "ZH/s"]
    idx = 0
    while hashrate >= 1000 and idx < len(units) - 1:
        hashrate /= 1000
        idx += 1
    return f"{hashrate:.2f} {units[idx]}"


def format_difficulty(difficulty: float | str) -> str:
    """Format difficulty into abbreviated notation."""
    try:
        d = float(difficulty)
        if d >= 1e12:
            return f"{d / 1e12:.2f}T"
        if d >= 1e9:
            return f"{d / 1e9:.2f}G"
        if d >= 1e6:
            return f"{d / 1e6:.2f}M"
        if d >= 1e3:
            return f"{d / 1e3:.2f}K"
        return f"{d:.2f}"
    except (ValueError, TypeError):
        return str(difficulty)


def format_duration(seconds: float) -> str:
    """Format a duration in seconds into a human-readable string."""
    if seconds < 0:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    if seconds < 86400:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"

    days = seconds / 86400
    if days < 30:
        d = int(days)
        h = int((seconds % 86400) // 3600)
        return f"{d}d {h}h"
    if days < 365:
        return f"{days / 30:.1f} months"

    years = days / 365
    if years >= 1_000_000:
        return f"{years / 1_000_000:.2f}M years"
    if years >= 1000:
        return f"{years / 1000:.2f}K years"
    return f"{years:.1f} years"


def calculate_uptime(start_time: str | None) -> str:
    """Calculate uptime from a startTime ISO string."""
    if not start_time:
        return "N/A"
    try:
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - start
        return format_duration(delta.total_seconds())
    except (ValueError, TypeError):
        return "N/A"


def check_worker_offline(last_seen: str | None) -> bool:
    """Check if a worker is offline based on lastSeen timestamp."""
    if not last_seen:
        return True
    try:
        last = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
        diff_min = (datetime.now(timezone.utc) - last).total_seconds() / 60
        return diff_min > OFFLINE_TIMEOUT_MINUTES
    except (ValueError, TypeError):
        return True


# ===========================================================================
# Telegram helpers
# ===========================================================================

def _telegram_post(method: str, data: dict | None = None) -> dict | None:
    """POST to the Telegram Bot API, retrying on 429 rate limits.

    Returns the parsed JSON response (which may have ok=False), or None on
    network/JSON failure. Retries at most twice, honoring retry_after.
    """
    for attempt in range(3):
        try:
            resp = requests.post(f"{TELEGRAM_API}/{method}", json=data, timeout=30)
            result = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.error("Telegram request failed (%s): %s", method, e)
            return None
        if (
            not result.get("ok")
            and result.get("error_code") == 429
            and attempt < 2
        ):
            retry_after = (result.get("parameters") or {}).get("retry_after", 1)
            wait = min(_safe_float(retry_after, 1.0), 30.0)
            logger.warning(
                "Telegram rate limit on %s, retrying in %.0fs", method, wait
            )
            time.sleep(wait)
            continue
        return result
    return None


def telegram_request(method: str, data: dict | None = None) -> dict | None:
    """Make a request to the Telegram Bot API."""
    result = _telegram_post(method, data)
    if result is None:
        return None
    if not result.get("ok"):
        logger.error("Telegram API error on %s: %s", method, result)
        return None
    return result.get("result")


def send_message(
    text: str, parse_mode: str = "HTML", reply_markup: dict | None = None
) -> dict | None:
    """Send a message to the configured group."""
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return telegram_request("sendMessage", payload)


def edit_message(message_id: int, text: str, parse_mode: str = "HTML") -> dict | None:
    """Edit an existing message. Returns sentinel on 'not modified' (no-op)."""
    result = _telegram_post("editMessageText", {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    })
    if result is None:
        return None
    if result.get("ok"):
        return result.get("result")
    desc = result.get("description", "")
    # Content unchanged is not an error - treat as success
    if "message is not modified" in desc:
        logger.debug("Message %s unchanged, skipping edit", message_id)
        return {"message_id": message_id}
    logger.error("Telegram API error on editMessageText: %s", result)
    return None


def delete_message(message_id: int) -> bool:
    """Delete a message. Returns True even if the message was already gone."""
    result = _telegram_post("deleteMessage", {
        "chat_id": CHAT_ID,
        "message_id": message_id,
    })
    if result is None:
        return False
    if result.get("ok"):
        return True
    # "message to delete not found" is expected (already deleted / >48h old)
    desc = result.get("description", "")
    if "message to delete not found" in desc:
        logger.debug("Message %s already deleted, ignoring", message_id)
        return True
    logger.error("Telegram API error on deleteMessage: %s", result)
    return False


def _delete_service_messages() -> None:
    """Delete pin/unpin service notification messages generated by the bot."""
    time.sleep(1)  # Give Telegram a moment to generate the service message
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/getUpdates", json={"timeout": 2}, timeout=10
        )
        updates = resp.json().get("result", [])
        if not updates:
            return
        for update in updates:
            msg = update.get("message", {})
            chat = msg.get("chat", {})
            if str(chat.get("id")) == str(CHAT_ID) and "pinned_message" in msg:
                delete_message(msg["message_id"])
        # Confirm all processed updates so they don't pile up
        max_update_id = max(u.get("update_id", 0) for u in updates)
        requests.post(
            f"{TELEGRAM_API}/getUpdates",
            json={"offset": max_update_id + 1, "timeout": 0},
            timeout=10,
        )
    except requests.RequestException:
        pass


def pin_message(message_id: int) -> bool:
    """Pin a message silently and delete the service notification."""
    result = telegram_request("pinChatMessage", {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "disable_notification": True,
    })
    if result is not None:
        _delete_service_messages()
        return True
    return False


def unpin_message(message_id: int) -> bool:
    """Unpin a message."""
    return telegram_request("unpinChatMessage", {
        "chat_id": CHAT_ID,
        "message_id": message_id,
    }) is not None


# ===========================================================================
# Update management (/update command, availability notifications)
# ===========================================================================

def _is_group_admin(user_id) -> bool:
    """Check whether a Telegram user is the group owner or an administrator."""
    if user_id is None:
        return False
    member = telegram_request("getChatMember", {
        "chat_id": CHAT_ID,
        "user_id": user_id,
    })
    if not member:
        return False
    return member.get("status") in ("creator", "administrator")


def _answer_callback(callback_id: str | None, text: str) -> None:
    """Answer a callback query, best-effort.

    Failures are ignored silently: since the bot runs on a schedule, the
    button press is usually answered many minutes later, when Telegram has
    already expired the query — that is expected, not an error.
    """
    if not callback_id:
        return
    try:
        requests.post(
            f"{TELEGRAM_API}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text},
            timeout=10,
        )
    except requests.RequestException:
        pass


def handle_telegram_updates() -> bool:
    """Process pending Telegram updates for the configured group.

    Only the /update command and the "Apply update" button are acted upon;
    every other message or command is ignored. Pending pin-notification
    service messages are deleted along the way. Any number of queued
    /update messages or button presses triggers a single update run.

    Returns True when an authorized request (group owner/admin) was received.
    """
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/getUpdates", json={"timeout": 2}, timeout=10
        )
        updates = resp.json().get("result", [])
    except (requests.RequestException, ValueError):
        return False
    if not updates:
        return False

    update_requested = False
    denied_notice_sent = False

    for update in updates:
        # --- "Apply update" inline button presses ---
        cq = update.get("callback_query") or {}
        if cq:
            cq_msg = cq.get("message") or {}
            cq_chat = cq_msg.get("chat") or {}
            if (
                str(cq_chat.get("id")) != str(CHAT_ID)
                or cq.get("data") != "apply_update"
            ):
                continue
            from_user = cq.get("from") or {}
            if _is_group_admin(from_user.get("id")):
                update_requested = True
                # Remove the button so the notification shows it was handled
                _telegram_post("editMessageReplyMarkup", {
                    "chat_id": CHAT_ID,
                    "message_id": cq_msg.get("message_id"),
                    "reply_markup": {"inline_keyboard": []},
                })
                _answer_callback(
                    cq.get("id"),
                    "Update queued ✓ It will be applied on the bot's next run.",
                )
                logger.warning(
                    "Apply-update button pressed by %s",
                    from_user.get("username") or from_user.get("id"),
                )
            else:
                _answer_callback(
                    cq.get("id"), "Only group admins can apply updates."
                )
                logger.warning(
                    "Apply-update button denied for user %s", from_user.get("id")
                )
            continue

        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        if str(chat.get("id")) != str(CHAT_ID):
            continue

        # Clean up pin-notification service messages left from previous runs
        if "pinned_message" in msg:
            delete_message(msg["message_id"])
            continue

        text = msg.get("text") or ""
        command = text.split()[0].split("@")[0].lower() if text.strip() else ""
        if command != "/update":
            continue  # every other message or command is ignored

        # Authorization: group owner/admin only. Messages sent as the group
        # itself (anonymous admins) always come from an admin.
        sender_chat = msg.get("sender_chat") or {}
        from_user = msg.get("from") or {}
        if str(sender_chat.get("id")) == str(CHAT_ID):
            authorized = True
        else:
            authorized = _is_group_admin(from_user.get("id"))

        if authorized:
            update_requested = True
            logger.warning(
                "/update command received from %s",
                from_user.get("username") or from_user.get("id") or "anonymous admin",
            )
        elif not denied_notice_sent:
            send_message("⛔ Only the group owner or an admin can run /update.")
            denied_notice_sent = True
            logger.warning("/update denied for user %s", from_user.get("id"))

    # Confirm all processed updates so they are not delivered again
    max_update_id = max(u.get("update_id", 0) for u in updates)
    try:
        requests.post(
            f"{TELEGRAM_API}/getUpdates",
            json={"offset": max_update_id + 1, "timeout": 0},
            timeout=10,
        )
    except requests.RequestException:
        pass

    return update_requested


def run_update_script(flag: str) -> bool:
    """Run update.sh with the given flag. Returns True if it exited cleanly.

    The update is applied on disk immediately; the running process keeps its
    old code, so changes take effect on the bot's next scheduled run.
    """
    script = SCRIPT_DIR / "update.sh"
    if not script.is_file():
        logger.error("update.sh not found, cannot update")
        return False
    try:
        result = subprocess.run(
            [str(script), flag],
            cwd=str(SCRIPT_DIR),
            timeout=300,
            capture_output=True,
        )
        logger.warning("update.sh %s finished with exit code %s", flag, result.returncode)
        return result.returncode == 0
    except Exception as e:
        logger.error("update.sh execution failed: %s", e)
        return False


def _git(*args: str, timeout: int = 30) -> str | None:
    """Run a git command in the bot directory. Returns stdout or None on error."""
    try:
        result = subprocess.run(
            ["git", "-C", str(SCRIPT_DIR), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except Exception:
        return None


def check_update_available() -> None:
    """Notify the group when a new version exists on the remote (once per version)."""
    if not (SCRIPT_DIR / ".git").is_dir():
        return
    if _git("fetch", "origin", timeout=60) is None:
        logger.warning("Update check: git fetch failed")
        return
    local = _git("rev-parse", "HEAD")
    remote = _git("rev-parse", "origin/main")
    if not local or not remote or local == remote:
        return
    commits = _git("log", "HEAD..origin/main", "--format=%h - %s")
    if not commits:
        return  # local is ahead of remote; nothing to apply
    if db.get_state("update_notified_hash") == remote:
        return  # this version was already announced

    remote_version = (_git("show", "origin/main:VERSION") or "unknown").strip()
    commit_list = commits.splitlines()
    commit_lines = "\n".join(
        f"  • <code>{html_escape(line)}</code>" for line in commit_list[:10]
    )
    if len(commit_list) > 10:
        commit_lines += f"\n  <i>...and {len(commit_list) - 10} more commit(s)</i>"

    send_message(
        f"🔔 <b>UPDATE AVAILABLE</b>\n\n"
        f"📦 <b>v{html_escape(BOT_VERSION)}  →  v{html_escape(remote_version)}</b>\n\n"
        f"🧾 <b>{len(commit_list)} new commit(s):</b>\n{commit_lines}\n\n"
        f"To apply it, either:\n"
        f"  • Tap the button below or send /update in this group "
        f"<i>(group owner/admin only)</i>. The command stays queued and "
        f"the update will run on the bot's next scheduled start "
        f"(within ~30 min).\n"
        f"  • Or run <code>update.sh</code> on the server to apply it immediately.",
        reply_markup={
            "inline_keyboard": [[
                {"text": "✅ Apply update", "callback_data": "apply_update"}
            ]]
        },
    )
    db.set_state("update_notified_hash", remote)
    logger.warning(
        "Update available notification sent (%s -> %s)", local[:7], remote[:7]
    )


# ===========================================================================
# API helpers
# ===========================================================================

def fetch_api_data(url: str) -> dict | None:
    """Fetch data from a public-pool.io API endpoint."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        logger.debug("API fetch OK: %s", url)
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.error("API request failed (%s): %s", url, e)
        return None


def fetch_pool_data() -> dict | None:
    """Fetch worker data for the configured BTC address."""
    return fetch_api_data(API_URL)


def fetch_pool_stats() -> dict | None:
    """Fetch pool-wide statistics."""
    return fetch_api_data(POOL_API_URL)


def fetch_network_stats() -> dict | None:
    """Fetch Bitcoin network statistics."""
    return fetch_api_data(NETWORK_API_URL)


# ===========================================================================
# Backup
# ===========================================================================

def backup_database() -> None:
    """Create a timestamped backup of the database and purge old backups.

    Skips backup creation if a backup younger than 24 hours already exists.
    """
    db_path = db.DB_FILE
    if not db_path.exists():
        return

    # Check if a recent backup (<24h) already exists
    cutoff_recent = datetime.now().timestamp() - 86400
    for f in BACKUP_DIR.iterdir():
        if f.suffix == ".db" and f.name.startswith("NerdMiners_Public_Pool_Stats_"):
            try:
                if f.stat().st_mtime > cutoff_recent:
                    logger.debug("Backup skipped: recent backup exists (%s)", f.name)
                    return
            except OSError:
                pass

    now = datetime.now().strftime("%m%d%Y_%H%M%S")
    backup_name = f"NerdMiners_Public_Pool_Stats_{now}.db"
    backup_path = BACKUP_DIR / backup_name

    try:
        shutil.copy2(str(db_path), str(backup_path))
        logger.info("Database backup created: %s", backup_name)
    except OSError as e:
        logger.error("Failed to create DB backup: %s", e)
        return

    # Purge backups older than BACKUP_RETENTION_DAYS
    cutoff = datetime.now().timestamp() - (BACKUP_RETENTION_DAYS * 86400)
    for f in BACKUP_DIR.iterdir():
        if f.suffix == ".db" and f.name.startswith("NerdMiners_"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    logger.debug("Purged old backup: %s", f.name)
            except OSError:
                pass


# ===========================================================================
# Worker identification
# ===========================================================================

def identify_workers(api_workers: list[dict]) -> dict[str, dict]:
    """
    Map each API worker to an internal ID and return a dict of
    {internal_id: worker_api_data}.

    Tracks already-assigned IDs to prevent two API workers from
    resolving to the same internal ID.
    """
    result = {}
    claimed_ids: set[str] = set()
    for w in api_workers:
        api_name = _safe_str(w.get("name"), "Unknown")
        session_id = _safe_str(w.get("sessionId"))
        hashrate = _safe_float(w.get("hashRate"))
        internal_id = db.resolve_worker_id(
            api_name, session_id, hashrate, api_workers, claimed_ids
        )
        claimed_ids.add(internal_id)
        result[internal_id] = w
        logger.debug("Worker resolved: '%s' → internal_id='%s'", api_name, internal_id)
    return result


# ===========================================================================
# Alert detection
# ===========================================================================

def check_alerts(identified_workers: dict[str, dict], pool_stats: dict | None) -> list[str]:
    """
    Compare current state against saved state and generate alert messages.
    Also handles session tracking, hashrate recording, and TOP 5 BD updates.
    Returns a list of alert message strings (HTML formatted).
    """
    alerts = []
    known_workers = {w["internal_id"] for w in db.get_active_workers()}
    current_ids = set(identified_workers.keys())

    # Workers whose tracking was resumed in this run; their session-change
    # alert is suppressed because the comeback alert already covers it.
    reactivated_ids: set[str] = set()

    # --- New miner detected / returning miner ---
    for new_id in current_ids - known_workers:
        w = identified_workers[new_id]
        display = get_display_name(new_id)
        hr = _safe_float(w.get("hashRate"))
        existing = db.get_worker(new_id)

        if existing and not existing.get("active", 1):
            # Known worker whose tracking was paused after disappearing
            db.set_worker_active(new_id, True)
            db.set_state(f"disappeared_count_{new_id}", "0")
            reactivated_ids.add(new_id)
            alerts.append(
                f"🔁 <b>MINER BACK ONLINE</b>\n"
                f"Miner: <b>{display}</b> ({html_escape(new_id)})\n"
                f"Hashrate: {format_hashrate(hr)}\n"
                f"<i>Tracking resumed — history and records were preserved.</i>"
            )
            logger.warning("Worker '%s' reappeared, tracking resumed", new_id)
        elif known_workers:
            alerts.append(
                f"🆕 <b>NEW MINER DETECTED</b>\n"
                f"Miner: <b>{display}</b> ({html_escape(new_id)})\n"
                f"Hashrate: {format_hashrate(hr)}"
            )

    # --- Missing miner ---
    _DISAPPEARED_MAX_ALERTS = 2
    if known_workers:
        for missing_id in known_workers - current_ids:
            display = get_display_name(missing_id)
            count_key = f"disappeared_count_{missing_id}"
            count = int(db.get_state(count_key, "0") or "0") + 1

            if count < _DISAPPEARED_MAX_ALERTS:
                db.set_state(count_key, str(count))
                alerts.append(
                    f"⚠️ <b>MINER DISAPPEARED</b>\n"
                    f"Miner: <b>{display}</b> ({html_escape(missing_id)})\n"
                    f"No longer visible in the pool"
                )
            else:
                # Final notice — pause tracking, keeping all history and records
                alerts.append(
                    f"⚠️ <b>MINER DISAPPEARED</b>\n"
                    f"Miner: <b>{display}</b> ({html_escape(missing_id)})\n"
                    f"No longer visible in the pool\n"
                    f"<i>This is the final notice. Tracking is paused; its history "
                    f"and records are preserved, and tracking will resume "
                    f"automatically if it reappears.</i>"
                )
                db.set_worker_active(missing_id, False)
                db.set_state(count_key, "0")
                logger.warning("Worker '%s' tracking paused after %d disappeared alerts", missing_id, count)

    # --- Per-worker checks ---
    for internal_id, w_data in identified_workers.items():
        display = get_display_name(internal_id)
        api_name = _safe_str(w_data.get("name"), "Unknown")
        session_id = _safe_str(w_data.get("sessionId"))
        hashrate = _safe_float(w_data.get("hashRate"))
        start_time = _safe_str(w_data.get("startTime"))
        last_seen = _safe_str(w_data.get("lastSeen"))
        w_best_diff = _safe_float(w_data.get("bestDifficulty"))

        saved_worker = db.get_worker(internal_id)

        # All-time best captured BEFORE the upsert below writes the current
        # best_diff into the DB; otherwise a new record could never exceed it
        prev_all_time = db.get_all_time_best(internal_id)

        # Worker is present — clear any pending disappeared strikes so a past
        # blip doesn't fast-track a future disappearance to the final notice
        count_key = f"disappeared_count_{internal_id}"
        if (db.get_state(count_key, "0") or "0") != "0":
            db.set_state(count_key, "0")

        # Ensure worker exists in DB before any FK-dependent operations
        db.upsert_worker(
            internal_id=internal_id,
            api_name=api_name,
            session_id=session_id,
            hashrate=hashrate,
            start_time=start_time,
            best_diff=w_best_diff,
            last_seen=last_seen,
        )

        # 24h average taken before recording the current sample, so the value
        # being checked doesn't drag down its own baseline
        avg_24h = db.get_avg_hashrate(internal_id, hours=24)

        # Record hashrate sample
        db.add_hashrate_sample(internal_id, hashrate)

        # --- Session change (disconnection) detection ---
        if saved_worker and saved_worker["last_start_time"] and start_time:
            if start_time != saved_worker["last_start_time"]:
                # Close previous session
                prev_best = saved_worker["last_best_diff"] or 0
                closed = db.close_session(internal_id, prev_best)

                # Calculate info for the alert
                prev_duration = "N/A"
                downtime_str = "N/A"
                if closed and closed["start_time"]:
                    try:
                        prev_start = datetime.fromisoformat(
                            closed["start_time"].replace("Z", "+00:00")
                        )
                        prev_last_seen = datetime.fromisoformat(
                            saved_worker["last_seen"].replace("Z", "+00:00")
                        ) if saved_worker["last_seen"] else None
                        new_start = datetime.fromisoformat(
                            start_time.replace("Z", "+00:00")
                        )

                        if prev_last_seen:
                            prev_duration = format_duration(
                                (prev_last_seen - prev_start).total_seconds()
                            )
                            downtime = (new_start - prev_last_seen).total_seconds()
                            if downtime > 0:
                                downtime_str = f"~{format_duration(downtime)}"
                    except (ValueError, TypeError):
                        pass

                new_start_fmt = "N/A"
                try:
                    ts = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    new_start_fmt = ts.strftime("%b %d, %Y %H:%M UTC")
                except (ValueError, TypeError):
                    pass

                if internal_id not in reactivated_ids:
                    alerts.append(
                        f"⚠️ <b>DISCONNECTION DETECTED</b>\n"
                        f"Miner: <b>{display}</b>\n"
                        f"Previous session: {prev_duration}\n"
                        f"Estimated downtime: {downtime_str}\n"
                        f"Reconnected at: {new_start_fmt}"
                    )

                # Open new session
                db.open_session(internal_id, session_id, start_time)

                # Update TOP 5 BD with previous session's best
                if prev_best > 0:
                    prev_session_id = saved_worker["last_session_id"] or ""
                    db.update_hall_of_fame(internal_id, prev_best, prev_session_id)

        elif not saved_worker or not db.get_current_session(internal_id):
            # First time seeing this worker, or no open session
            if start_time:
                db.open_session(internal_id, session_id, start_time)

        # --- Worker offline (a single notice per outage, reset on recovery) ---
        offline_key = f"offline_alerted_{internal_id}"
        if check_worker_offline(last_seen):
            if (db.get_state(offline_key, "0") or "0") != "1":
                db.set_state(offline_key, "1")
                alerts.append(
                    f"🔴 <b>MINER OFFLINE</b>\n"
                    f"Miner: <b>{display}</b>\n"
                    f"No activity for more than {OFFLINE_TIMEOUT_MINUTES} minutes\n"
                    f"<i>No more reminders will be sent until it comes back online.</i>"
                )
        elif (db.get_state(offline_key, "0") or "0") != "0":
            db.set_state(offline_key, "0")

        # --- Hashrate drop (vs 24h average) ---
        if avg_24h and avg_24h > 0 and hashrate > 0:
            drop = ((avg_24h - hashrate) / avg_24h) * 100
            strikes_key = f"low_hashrate_strikes_{internal_id}"
            alerted_key = f"low_hashrate_alerted_at_{internal_id}"

            if drop >= HASHRATE_DROP_PERCENT:
                strikes = int(db.get_state(strikes_key, "0") or "0") + 1
                db.set_state(strikes_key, str(strikes))
                logger.debug(
                    "Low hashrate strike %d/%d for %s (drop=%.1f%%)",
                    strikes, HASHRATE_ALERT_STRIKES, internal_id, drop,
                )

                if strikes >= HASHRATE_ALERT_STRIKES:
                    can_alert = True
                    alerted_at_str = db.get_state(alerted_key)
                    if alerted_at_str:
                        try:
                            alerted_at = datetime.fromisoformat(alerted_at_str)
                            elapsed_h = (
                                datetime.now(timezone.utc) - alerted_at
                            ).total_seconds() / 3600
                            if elapsed_h < HASHRATE_ALERT_COOLDOWN_HOURS:
                                can_alert = False
                                logger.debug(
                                    "Low hashrate alert suppressed for %s: cooldown active (%.1fh remaining)",
                                    internal_id, HASHRATE_ALERT_COOLDOWN_HOURS - elapsed_h,
                                )
                        except (ValueError, TypeError):
                            pass

                    if can_alert:
                        db.set_state(alerted_key, datetime.now(timezone.utc).isoformat())
                        alerts.append(
                            f"📉 <b>LOW HASHRATE</b>\n"
                            f"Miner: <b>{display}</b>\n"
                            f"Current: {format_hashrate(hashrate)}\n"
                            f"24h average: {format_hashrate(avg_24h)}\n"
                            f"Drop: {drop:.1f}%"
                        )
            else:
                # Hashrate recovered — reset strike counter and cooldown
                db.set_state(strikes_key, "0")
                db.set_state(alerted_key, "")

        # --- New personal best difficulty (current session) ---
        if saved_worker:
            saved_best = saved_worker["last_best_diff"] or 0
            if w_best_diff > saved_best and saved_best > 0:
                is_all_time = w_best_diff > prev_all_time

                if is_all_time or NOTIFY_SESSION_BD_RECORD:
                    msg = (
                        f"🌟 <b>NEW PERSONAL RECORD!</b>\n"
                        f"Miner: <b>{display}</b>\n"
                        f"Session Best Difficulty: {format_difficulty(w_best_diff)}\n"
                        f"Previous: {format_difficulty(saved_best)}"
                    )
                    if is_all_time:
                        msg += "\n🏆 <b>New All-Time Best!</b>"
                    alerts.append(msg)

                # Update TOP 5 BD (always, regardless of notification setting)
                db.update_hall_of_fame(internal_id, w_best_diff, session_id)

    # --- Pool block found ---
    if pool_stats:
        current_blocks = pool_stats.get("blocksFound") or []
        if current_blocks:
            known_heights = db.get_known_pool_block_heights()
            # On a brand-new database, record the pool's historical blocks
            # without alerting: they were found before the bot started
            seeding = (
                not known_heights and db.get_state("pool_blocks_seeded") is None
            )
            for block in current_blocks:
                if not isinstance(block, dict):
                    continue
                height = block.get("height")
                if height is None or height in known_heights:
                    continue
                db.save_pool_block(block)
                if seeding:
                    continue
                miner_address = block.get("minerAddress", "")
                worker_name = block.get("worker", "")

                if miner_address == BTC_ADDRESS:
                    display = get_display_name(worker_name) if worker_name else "Unknown"
                    alerts.append(
                        f"🏆🏆🏆 <b>YOUR MINER FOUND A BLOCK!</b> 🏆🏆🏆\n\n"
                        f"🎉 <b>CONGRATULATIONS!</b> 🎉\n"
                        f"Block: <b>#{height}</b>\n"
                        f"Miner: <b>{display}</b>"
                    )
                else:
                    alerts.append(
                        f"⛏️ <b>BLOCK FOUND BY THE POOL</b>\n"
                        f"Block: #{height}\n"
                        f"Unfortunately it was not one of your miners."
                    )
            if db.get_state("pool_blocks_seeded") is None:
                db.set_state("pool_blocks_seeded", "1")

    return alerts


# ===========================================================================
# Stats message builder
# ===========================================================================

def build_stats_message(
    identified_workers: dict[str, dict],
    pool_data: dict,
    pool_stats: dict | None,
    network_stats: dict | None,
) -> str:
    """Build the formatted statistics message for Telegram."""
    workers_count = int(_safe_float(pool_data.get("workersCount")))
    now = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M:%S UTC")

    my_total_hashrate = sum(
        _safe_float(w.get("hashRate")) for w in identified_workers.values()
    )

    # All-time best across all workers
    global_best = 0.0
    global_best_worker = ""
    hof = db.get_hall_of_fame(limit=1)
    if hof:
        entry = hof[0]
        global_best = entry["difficulty"]
        global_best_worker = get_display_name(entry["worker_id"])

    # Total 24h average
    total_avg = 0.0
    for wid in identified_workers:
        avg = db.get_avg_hashrate(wid, hours=24)
        if avg:
            total_avg += avg

    lines = [
        "<blockquote>⛏️ <b>NerdMiners Stats</b></blockquote>",
        f"📅 {now}",
        "━━━━━━━━━━━━━━",
    ]

    if global_best > 0:
        best_info = format_difficulty(global_best)
        if global_best_worker:
            best_info += f"\n          └ <i>{global_best_worker}</i>"
        lines.append(f"   🏆 <b>All-Time Best Diff:</b> {best_info}")

    lines.append(f"   👷 <b>Workers:</b> {workers_count}")
    lines.append(f"   ⚡ <b>Total Hashrate:</b> {format_hashrate(my_total_hashrate)}")
    if total_avg > 0:
        lines.append(f"          └ <i>24h Avg Hashrate: {format_hashrate(total_avg)}</i>")

    # Pool stats
    if pool_stats:
        pool_hashrate = _safe_float(pool_stats.get("totalHashRate"))
        total_miners = int(_safe_float(pool_stats.get("totalMiners")))
        contribution = (
            (my_total_hashrate / pool_hashrate * 100) if pool_hashrate > 0 else 0
        )
        lines += [
            "",
            "<b>━━━ Pool Stats ━━━</b>",
            f"   🌐 <b>Pool Hashrate</b>: {format_hashrate(pool_hashrate)}",
            f"   👥 <b>Total Miners</b>: {total_miners:,}",
            f"   📊 <b>Your contribution</b>: {contribution:.6f}%",
        ]

    # Network stats
    if network_stats:
        net_diff = _safe_float(network_stats.get("difficulty"))
        net_hashrate = _safe_float(network_stats.get("networkhashps"))
        block_height = int(_safe_float(network_stats.get("blocks")))
        lines += [
            "",
            "<b>━━━ Bitcoin Network ━━━</b>",
            f"   🔗 <b>Block</b>: #{block_height:,}",
            f"   💪 <b>Difficulty</b>: {format_difficulty(net_diff)}",
            f"   🌍 <b>Network Hashrate</b>: {format_hashrate(net_hashrate)}",
        ]

    lines.append("")

    # Per-worker stats
    for internal_id, w_data in identified_workers.items():
        display = get_display_name(internal_id)
        hashrate = _safe_float(w_data.get("hashRate"))
        session_best = _safe_float(w_data.get("bestDifficulty"))
        start_time = _safe_str(w_data.get("startTime"))
        last_seen = _safe_str(w_data.get("lastSeen"))

        uptime = calculate_uptime(start_time)
        is_offline = check_worker_offline(last_seen)
        status = "🔴 <b>OFFLINE</b>" if is_offline else "🟢 <b>Online</b>"

        all_time_best = db.get_all_time_best(internal_id)
        all_time_best = max(all_time_best, session_best)
        avg_hr = db.get_avg_hashrate(internal_id, hours=24)
        uptime_pct = db.get_uptime_percent(internal_id, days=UPTIME_WINDOW_DAYS)

        hr_line = f"   ⚡ <b>Hashrate</b>: {format_hashrate(hashrate)}"
        if avg_hr and avg_hr > 0:
            hr_line += f"\n          └ <i>24h avg: {format_hashrate(avg_hr)}</i>"

        diff_line = f"   🎯 <b>Best Difficulty</b>: {format_difficulty(all_time_best)}"
        diff_line += f"\n          └ <i>Current session: {format_difficulty(session_best)}</i>"

        lines += [
            f"<b>━━━ {display} ━━━</b>",
            f"   {status}",
            hr_line,
            diff_line,
            f"   ⏱️ <b>Current Session Uptime</b>: {uptime}",
        ]
        if uptime_pct is not None:
            lines.append(
                f"   📊 <b>Uptime {UPTIME_WINDOW_DAYS}d</b>: {uptime_pct:.1f}%"
            )
        lines.append("")

    # TOP N BD
    _top_bd = min(max(int(SHOW_TOP_BD), 1), 10)
    hof_entries = db.get_hall_of_fame(limit=_top_bd)
    if hof_entries:
        lines.append(f"<b>━━━ TOP {_top_bd} BD ━━━</b>")
        for i, entry in enumerate(hof_entries, 1):
            w_name = get_display_name(entry["worker_id"])
            diff = format_difficulty(entry["difficulty"])
            date_str = ""
            try:
                dt = datetime.fromisoformat(
                    entry["achieved_at"].replace("Z", "+00:00")
                )
                date_str = dt.strftime("%b %d, %Y")
            except (ValueError, TypeError):
                pass
            lines.append(f"   {i}. {diff} - {w_name} ({date_str})")
        lines.append("")

    lines.append(f"<i>NerdMiners Bot v{html_escape(BOT_VERSION)}</i>")

    return "\n".join(lines)


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    """Main entry point for the bot."""
    # Ensure all shell scripts stay executable by the owner
    for _sh in SCRIPT_DIR.glob("*.sh"):
        _sh.chmod(_sh.stat().st_mode | 0o100)

    # Self-heal the environment (directories, venv, dependencies, permissions).
    # A heal failure must never prevent the bot from running.
    _install_script = SCRIPT_DIR / "install.sh"
    if _install_script.is_file():
        try:
            subprocess.run(
                [str(_install_script), "--heal"],
                cwd=str(SCRIPT_DIR),
                timeout=120,
                capture_output=True,
            )
        except Exception:
            pass

    logger.info("=== Bot run started (v%s) ===", BOT_VERSION)

    # Validate configuration
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not configured in .env")
        return
    if not CHAT_ID:
        logger.error("CHAT_ID not configured in .env")
        return
    if not BTC_ADDRESS:
        logger.error("BTC_ADDRESS not configured in .env")
        return

    # Initialize database
    db.init_db()

    # Create database backup
    backup_database()

    # --- Updates ---
    # Read pending group messages: queued /update commands (owner/admin only)
    # and leftover pin-notification service messages.
    update_requested = handle_telegram_updates()

    if UPDATE_MODE == "auto":
        # Legacy behavior: apply updates automatically on every run
        run_update_script("--auto")
    elif update_requested:
        send_message(
            "🔄 <b>Update requested</b> — applying now...\n"
            "<i>Changes take effect on the bot's next scheduled run.</i>"
        )
        run_update_script("--from-telegram")
    else:
        # Manual mode: announce new versions once, let the admin decide
        check_update_available()

    # Fetch data from APIs
    pool_data = fetch_pool_data()
    if not pool_data:
        logger.error("Failed to fetch pool data from API")
        return

    pool_stats = fetch_pool_stats()
    if not pool_stats:
        logger.warning("Pool stats unavailable, some data may be missing")

    network_stats = fetch_network_stats()
    if not network_stats:
        logger.warning("Network stats unavailable, some data may be missing")

    # Identify workers (handle duplicate names)
    api_workers = pool_data.get("workers") or []
    identified = identify_workers(api_workers)

    if identified:
        logger.info("Workers found: %d (%s)", len(identified), ", ".join(identified.keys()))
    else:
        logger.warning("No workers found for configured BTC address")

    # Check alerts and update state
    alerts = check_alerts(identified, pool_stats)

    # Send alerts
    if not alerts:
        logger.info("No alerts this run")
    for alert in alerts:
        result = send_message(alert)
        if result:
            logger.warning("Alert sent: %s", alert[:80].replace("\n", " "))

    # Build stats message
    stats_message = build_stats_message(identified, pool_data, pool_stats, network_stats)

    # Manage stats message (edit or recreate)
    message_id_str = db.get_state("message_id")
    message_ts_str = db.get_state("message_timestamp")

    try:
        message_id = int(message_id_str) if message_id_str else None
    except (ValueError, TypeError):
        message_id = None
    try:
        message_ts = float(message_ts_str) if message_ts_str else None
    except (ValueError, TypeError):
        message_ts = None

    now_ts = datetime.now(timezone.utc).timestamp()
    message_too_old = (
        message_ts is not None and (now_ts - message_ts) > MESSAGE_EDIT_LIMIT
    )

    if message_id and not message_too_old:
        # Try to edit existing message
        result = edit_message(message_id, stats_message)
        if result:
            logger.info("Stats message edited (id=%s)", message_id)
            # Watchdog: if the group has no pinned message at all (someone
            # unpinned it by hand), pin the stats message again. If another
            # message is pinned we leave it alone (multi-pin is allowed and
            # we don't want to fight the user's own pins).
            chat_info = telegram_request("getChat", {"chat_id": CHAT_ID})
            if chat_info is not None and not chat_info.get("pinned_message"):
                pin_message(message_id)
                logger.warning("Stats message was unpinned externally; pinned it again")
        else:
            # Edit failed, send new message
            logger.warning("Could not edit message %s, sending new one", message_id)
            result = send_message(stats_message)
            if result:
                new_id = result.get("message_id")
                unpin_message(message_id)
                pin_message(new_id)
                db.set_state("message_id", str(new_id))
                db.set_state("message_timestamp", str(now_ts))
                logger.info("Stats message sent (new id=%s)", new_id)
    else:
        # Delete old message if exists
        if message_id:
            unpin_message(message_id)
            if not delete_message(message_id):
                logger.warning("Could not delete old message %s", message_id)

        # Send new message and pin it
        result = send_message(stats_message)
        if result:
            new_id = result.get("message_id")
            pin_message(new_id)
            db.set_state("message_id", str(new_id))
            db.set_state("message_timestamp", str(now_ts))
            logger.info("Stats message sent (new id=%s)", new_id)

    # Purge old data
    purged = db.purge_old_data(DATA_RETENTION_DAYS)
    if purged > 0:
        logger.warning("Purged %d old hashrate samples", purged)

    logger.info("=== Bot run completed ===")


if __name__ == "__main__":
    main()
