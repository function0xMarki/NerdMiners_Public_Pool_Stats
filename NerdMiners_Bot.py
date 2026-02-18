#!/usr/bin/env python3
"""
NerdMiners_Public_Pool_Stats Bot Telegram Bot.
Monitors Bitcoin miners on public-pool.io and sends statistics and alerts
to a Telegram group. Designed to run periodically via cron.
"""

import logging
import os
import shutil
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
    HASHRATE_DROP_PERCENT,
    LOG_LEVEL,
    MESSAGE_EDIT_LIMIT_HOURS,
    NAME_SUBSTITUTIONS,
    OFFLINE_TIMEOUT_MINUTES,
)

# Load environment variables
load_dotenv()

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

def telegram_request(method: str, data: dict | None = None) -> dict | None:
    """Make a request to the Telegram Bot API."""
    try:
        resp = requests.post(f"{TELEGRAM_API}/{method}", json=data, timeout=30)
        result = resp.json()
        if not result.get("ok"):
            logger.error("Telegram API error on %s: %s", method, result)
            return None
        return result.get("result")
    except requests.RequestException as e:
        logger.error("Telegram request failed (%s): %s", method, e)
        return None


def send_message(text: str, parse_mode: str = "HTML") -> dict | None:
    """Send a message to the configured group."""
    return telegram_request("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
    })


def edit_message(message_id: int, text: str, parse_mode: str = "HTML") -> dict | None:
    """Edit an existing message. Returns sentinel on 'not modified' (no-op)."""
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/editMessageText",
            json={
                "chat_id": CHAT_ID,
                "message_id": message_id,
                "text": text,
                "parse_mode": parse_mode,
            },
            timeout=30,
        )
        result = resp.json()
        if result.get("ok"):
            return result.get("result")
        desc = result.get("description", "")
        # Content unchanged is not an error - treat as success
        if "message is not modified" in desc:
            logger.debug("Message %s unchanged, skipping edit", message_id)
            return {"message_id": message_id}
        logger.error("Telegram API error on editMessageText: %s", result)
        return None
    except requests.RequestException as e:
        logger.error("Telegram request failed (editMessageText): %s", e)
        return None


def delete_message(message_id: int) -> bool:
    """Delete a message. Returns True even if the message was already gone."""
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/deleteMessage",
            json={"chat_id": CHAT_ID, "message_id": message_id},
            timeout=30,
        )
        result = resp.json()
        if result.get("ok"):
            return True
        # "message to delete not found" is expected (already deleted / >48h old)
        desc = result.get("description", "")
        if "message to delete not found" in desc:
            logger.debug("Message %s already deleted, ignoring", message_id)
            return True
        logger.error("Telegram API error on deleteMessage: %s", result)
        return False
    except requests.RequestException as e:
        logger.error("Telegram request failed (deleteMessage): %s", e)
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
# API helpers
# ===========================================================================

def fetch_api_data(url: str) -> dict | None:
    """Fetch data from a public-pool.io API endpoint."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
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
                    return
            except OSError:
                pass

    now = datetime.now().strftime("%d%m%Y_%H%M%S")
    backup_name = f"NerdMiners_Public_Pool_Stats_{now}.db"
    backup_path = BACKUP_DIR / backup_name

    try:
        shutil.copy2(str(db_path), str(backup_path))
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
    return result


# ===========================================================================
# Alert detection
# ===========================================================================

def check_alerts(identified_workers: dict[str, dict], pool_stats: dict | None) -> list[str]:
    """
    Compare current state against saved state and generate alert messages.
    Also handles session tracking, hashrate recording, and hall of fame updates.
    Returns a list of alert message strings (HTML formatted).
    """
    alerts = []
    known_workers = {w["internal_id"] for w in db.get_all_workers()}
    current_ids = set(identified_workers.keys())

    # --- New miner detected ---
    if known_workers:
        for new_id in current_ids - known_workers:
            w = identified_workers[new_id]
            display = get_display_name(new_id)
            hr = _safe_float(w.get("hashRate"))
            alerts.append(
                f"🆕 <b>NEW MINER DETECTED</b>\n"
                f"Miner: <b>{display}</b> ({html_escape(new_id)})\n"
                f"Hashrate: {format_hashrate(hr)}"
            )

    # --- Missing miner ---
    if known_workers:
        for missing_id in known_workers - current_ids:
            display = get_display_name(missing_id)
            alerts.append(
                f"⚠️ <b>MINER DISAPPEARED</b>\n"
                f"Miner: <b>{display}</b> ({html_escape(missing_id)})\n"
                f"No longer visible in the pool"
            )

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
                    new_start_fmt = ts.strftime("%d/%m/%Y %H:%M UTC")
                except (ValueError, TypeError):
                    pass

                alerts.append(
                    f"⚠️ <b>DISCONNECTION DETECTED</b>\n"
                    f"Miner: <b>{display}</b>\n"
                    f"Previous session: {prev_duration}\n"
                    f"Estimated downtime: {downtime_str}\n"
                    f"Reconnected at: {new_start_fmt}"
                )

                # Open new session
                db.open_session(internal_id, session_id, start_time)

                # Update hall of fame with previous session's best
                if prev_best > 0:
                    prev_session_id = saved_worker["last_session_id"] or ""
                    db.update_hall_of_fame(internal_id, prev_best, prev_session_id)

        elif not saved_worker or not db.get_current_session(internal_id):
            # First time seeing this worker, or no open session
            if start_time:
                db.open_session(internal_id, session_id, start_time)

        # --- Worker offline ---
        if check_worker_offline(last_seen):
            alerts.append(
                f"🔴 <b>MINER OFFLINE</b>\n"
                f"Miner: <b>{display}</b>\n"
                f"No activity for more than {OFFLINE_TIMEOUT_MINUTES} minutes"
            )

        # --- Hashrate drop (vs 24h average) ---
        avg_24h = db.get_avg_hashrate(internal_id, hours=24)
        if avg_24h and avg_24h > 0 and hashrate > 0:
            drop = ((avg_24h - hashrate) / avg_24h) * 100
            if drop >= HASHRATE_DROP_PERCENT:
                alerts.append(
                    f"📉 <b>LOW HASHRATE</b>\n"
                    f"Miner: <b>{display}</b>\n"
                    f"Current: {format_hashrate(hashrate)}\n"
                    f"24h average: {format_hashrate(avg_24h)}\n"
                    f"Drop: {drop:.1f}%"
                )

        # --- New personal best difficulty (current session) ---
        if saved_worker:
            saved_best = saved_worker["last_best_diff"] or 0
            if w_best_diff > saved_best and saved_best > 0:
                all_time = db.get_all_time_best(internal_id)
                is_all_time = w_best_diff > all_time
                msg = (
                    f"🌟 <b>NEW PERSONAL RECORD!</b>\n"
                    f"Miner: <b>{display}</b>\n"
                    f"Session Best: {format_difficulty(w_best_diff)}\n"
                    f"Previous: {format_difficulty(saved_best)}"
                )
                if is_all_time:
                    msg += "\n🏆 <b>New All-Time Best!</b>"
                alerts.append(msg)

                # Update hall of fame
                db.update_hall_of_fame(internal_id, w_best_diff, session_id)

    # --- Pool block found ---
    if pool_stats:
        current_blocks = pool_stats.get("blocksFound") or []
        if current_blocks:
            known_heights = db.get_known_pool_block_heights()
            for block in current_blocks:
                if not isinstance(block, dict):
                    continue
                height = block.get("height")
                if height is None or height in known_heights:
                    continue
                db.save_pool_block(block)
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
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")

    my_total_hashrate = sum(
        _safe_float(w.get("hashRate")) for w in identified_workers.values()
    )

    # All-time best across all workers
    global_best = 0.0
    global_best_worker = ""
    global_best_date = ""
    hof = db.get_hall_of_fame(limit=1)
    if hof:
        entry = hof[0]
        global_best = entry["difficulty"]
        global_best_worker = get_display_name(entry["worker_id"])
        try:
            dt = datetime.fromisoformat(entry["achieved_at"].replace("Z", "+00:00"))
            global_best_date = dt.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            global_best_date = ""

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
            best_info += f" ({global_best_worker}"
            if global_best_date:
                best_info += f", {global_best_date}"
            best_info += ")"
        lines.append(f"   🏆 <b>All-Time Best Diff:</b> {best_info}")

    lines.append(f"   👷 <b>Workers:</b> {workers_count}")
    lines.append(f"   ⚡ <b>Total Hashrate:</b> {format_hashrate(my_total_hashrate)}")
    if total_avg > 0:
        lines.append(f"   📊 <b>24h Avg Hashrate:</b> {format_hashrate(total_avg)}")

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
            f"   🌐 Pool Hashrate: {format_hashrate(pool_hashrate)}",
            f"   👥 Total Miners: {total_miners:,}",
            f"   📊 Your contribution: {contribution:.6f}%",
        ]

    # Network stats
    if network_stats:
        net_diff = _safe_float(network_stats.get("difficulty"))
        net_hashrate = _safe_float(network_stats.get("networkhashps"))
        block_height = int(_safe_float(network_stats.get("blocks")))
        lines += [
            "",
            "<b>━━━ Bitcoin Network ━━━</b>",
            f"   🔗 Block: #{block_height:,}",
            f"   💪 Difficulty: {format_difficulty(net_diff)}",
            f"   🌍 Network Hashrate: {format_hashrate(net_hashrate)}",
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
        status = "🔴 OFFLINE" if is_offline else "🟢 Online"

        all_time_best = db.get_all_time_best(internal_id)
        all_time_best = max(all_time_best, session_best)
        avg_hr = db.get_avg_hashrate(internal_id, hours=24)

        hr_line = f"   ⚡ Hashrate: {format_hashrate(hashrate)}"
        if avg_hr and avg_hr > 0:
            hr_line += f" (24h avg: {format_hashrate(avg_hr)})"

        diff_line = f"   🎯 Session Best: {format_difficulty(session_best)}"
        diff_line += f" | All-Time: {format_difficulty(all_time_best)}"

        lines += [
            f"<b>━━━ {display} ━━━</b>",
            f"   {status}",
            hr_line,
            diff_line,
            f"   ⏱️ Uptime: {uptime} (session)",
            "",
        ]

    # Hall of Fame (top 3 in message)
    hof_entries = db.get_hall_of_fame(limit=3)
    if hof_entries:
        lines.append("<b>━━━ Hall of Fame ━━━</b>")
        for i, entry in enumerate(hof_entries, 1):
            w_name = get_display_name(entry["worker_id"])
            diff = format_difficulty(entry["difficulty"])
            date_str = ""
            try:
                dt = datetime.fromisoformat(
                    entry["achieved_at"].replace("Z", "+00:00")
                )
                date_str = dt.strftime("%d/%m/%Y")
            except (ValueError, TypeError):
                pass
            lines.append(f"   {i}. {diff} - {w_name} ({date_str})")

    return "\n".join(lines)


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    """Main entry point for the bot."""
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

    # Fetch data from APIs
    pool_data = fetch_pool_data()
    if not pool_data:
        logger.error("Failed to fetch pool data from API")
        return

    pool_stats = fetch_pool_stats()
    network_stats = fetch_network_stats()

    # Identify workers (handle duplicate names)
    api_workers = pool_data.get("workers") or []
    identified = identify_workers(api_workers)

    # Check alerts and update state
    alerts = check_alerts(identified, pool_stats)

    # Send alerts
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
        if not result:
            # Edit failed, send new message
            logger.warning("Could not edit message %s, sending new one", message_id)
            result = send_message(stats_message)
            if result:
                new_id = result.get("message_id")
                unpin_message(message_id)
                pin_message(new_id)
                db.set_state("message_id", str(new_id))
                db.set_state("message_timestamp", str(now_ts))
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

    # Purge old data
    purged = db.purge_old_data(DATA_RETENTION_DAYS)
    if purged > 0:
        logger.warning("Purged %d old hashrate samples", purged)


if __name__ == "__main__":
    main()
