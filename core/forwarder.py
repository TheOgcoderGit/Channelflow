"""
ChannelFlow AI - Forward Engine
=================================

Listens for new messages on every enabled source of every active
project (through the single shared Telethon client - see
``core.client``) and forwards/copies them into that project's enabled
destinations, applying:

    * Media type / keyword / regex filters
    * Fixed or random delay
    * Media-group ("album") batching
    * Forward vs Copy mode, with optional silent + protect-content
    * Automatic retry with FloodWait handling
    * Per-project logging and stats

Performance notes
------------------
The previous implementation ran a fresh SQL query per *project* for
every single incoming message (``get_active_projects`` then, per
project, ``get_sources``). On an account with many projects that's
O(projects) queries per message. This version keeps a small in-memory
routing cache (chat_id -> project routing info) that is rebuilt from
the database on a timer, so the hot path for each incoming message is
a dict lookup, not a database round-trip.
"""

import asyncio
import logging
import random
import re
import time

from telethon import events
from telethon.errors import FloodWaitError, RPCError

from core.client import client, ensure_started
from database.db import get_connection
from services import log_service, stats_service, project_service
from bot import notifier

logger = logging.getLogger(__name__)

CACHE_REFRESH_SECONDS = 5
ALBUM_DEBOUNCE_SECONDS = 1.2
MAX_SEND_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds, doubles each attempt


# ==========================================
# ROUTING CACHE
# ==========================================
#
# _ROUTES maps a source chat_id (str) -> list of routing dicts, one per
# active project that listens to it:
#   {
#     "project_id": int,
#     "destinations": [int, ...],
#     "settings": dict (project_settings row),
#   }

_ROUTES = {}
_routes_lock = asyncio.Lock()


def _load_routes_sync():
    """
    Synchronous DB read building the full routing table in one pass.
    Runs off the event loop via asyncio.to_thread so a slow disk never
    stalls message dispatch.
    """

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM projects WHERE status=1")
    active_project_ids = [row["id"] for row in cur.fetchall()]

    routes = {}

    for project_id in active_project_ids:

        cur.execute(
            "SELECT chat_id FROM sources WHERE project_id=? AND enabled=1",
            (project_id,)
        )
        sources = [str(row["chat_id"]) for row in cur.fetchall()]

        if not sources:
            continue

        cur.execute(
            "SELECT chat_id FROM destinations WHERE project_id=? AND enabled=1",
            (project_id,)
        )
        destinations = [int(row["chat_id"]) for row in cur.fetchall()]

        if not destinations:
            continue

        cur.execute(
            "SELECT * FROM project_settings WHERE project_id=?",
            (project_id,)
        )
        settings = cur.fetchone()

        if settings is None:
            cur.execute(
                "INSERT INTO project_settings(project_id) VALUES(?)",
                (project_id,)
            )
            conn.commit()
            cur.execute(
                "SELECT * FROM project_settings WHERE project_id=?",
                (project_id,)
            )
            settings = cur.fetchone()

        route = {
            "project_id": project_id,
            "destinations": destinations,
            "settings": dict(settings),
        }

        for chat_id in sources:
            routes.setdefault(chat_id, []).append(route)

    conn.close()

    return routes


async def _refresh_routes():

    global _ROUTES

    try:
        routes = await asyncio.to_thread(_load_routes_sync)
    except Exception:
        logger.exception("Failed to refresh routing cache")
        return

    async with _routes_lock:
        _ROUTES = routes


async def _routes_refresh_loop():

    while True:

        await _refresh_routes()
        await asyncio.sleep(CACHE_REFRESH_SECONDS)


async def force_refresh_routes():
    """Called by the bot after a create/start/stop/edit action so the
    engine doesn't wait up to CACHE_REFRESH_SECONDS to notice."""

    await _refresh_routes()


# ==========================================
# FILTER ENGINE
# ==========================================

def _media_type_of(message):

    if message.photo:
        return "photo"

    if message.voice:
        return "voice"

    if message.video_note:
        return "video_note"

    if message.gif:
        return "animation"

    if message.sticker:
        return "sticker"

    if message.video:
        return "video"

    if message.audio:
        return "audio"

    if message.document:
        return "document"

    if message.poll:
        return "poll"

    if message.text:
        return "text"

    return "other"


def _passes_media_filter(message, settings):

    media_filter = settings.get("media_filter") or "all"

    if media_filter == "all":
        return True

    return _media_type_of(message) == media_filter


def _passes_keyword_filters(message, settings):

    text = (message.raw_text or "").lower()

    whitelist = [
        w.strip().lower()
        for w in (settings.get("keyword_whitelist") or "").split(",")
        if w.strip()
    ]

    if whitelist and not any(w in text for w in whitelist):
        return False

    blacklist = [
        w.strip().lower()
        for w in (settings.get("keyword_blacklist") or "").split(",")
        if w.strip()
    ]

    if blacklist and any(w in text for w in blacklist):
        return False

    return True


def _passes_regex_filter(message, settings):

    pattern = (settings.get("regex_filter") or "").strip()

    if not pattern:
        return True

    try:
        return re.search(pattern, message.raw_text or "") is not None
    except re.error:
        logger.warning("Invalid regex filter %r - treating as pass", pattern)
        return True


def _passes_all_filters(message, settings):

    return (
        _passes_media_filter(message, settings)
        and _passes_keyword_filters(message, settings)
        and _passes_regex_filter(message, settings)
    )


# ==========================================
# OWNER ALERTS
# ==========================================

async def _alert_owner(project_id, destination, text):
    """Pushes a real Telegram DM to whoever owns this project, so a
    forwarding problem is seen immediately instead of only living in
    the 📜 Logs screen. Throttled per (project, destination) so a
    chat failing on every message doesn't spam the owner."""

    try:
        project = project_service.get_project(project_id)
    except Exception:
        logger.exception("Could not look up owner for project %s", project_id)
        return

    if not project:
        return

    await notifier.notify_user(
        project["user_id"],
        text,
        throttle_key=f"forward_fail:{project_id}:{destination}",
    )


# ==========================================
# SEND WITH RETRY
# ==========================================

async def _send_with_retry(coro_factory, project_id, destination):
    """
    coro_factory: zero-arg callable returning a fresh awaitable each
    call (needed because a coroutine object can only be awaited once,
    and retries need a new one).
    """

    attempt = 0

    while True:

        try:
            return await coro_factory()

        except FloodWaitError as e:

            wait_for = e.seconds + 1

            log_service.add_log(
                project_id, "retry",
                f"FloodWait on {destination}: sleeping {wait_for}s"
            )
            stats_service.increment(project_id, "retried")

            await asyncio.sleep(wait_for)
            # FloodWait doesn't count against MAX_SEND_RETRIES - it's
            # not a failure, just Telegram enforcing pacing.
            continue

        except RPCError as e:

            attempt += 1

            if attempt > MAX_SEND_RETRIES:

                log_service.add_log(
                    project_id, "error",
                    f"Send to {destination} failed after {MAX_SEND_RETRIES} retries: {e}"
                )
                stats_service.increment(project_id, "failed")

                await _alert_owner(
                    project_id, destination,
                    "⚠ ChannelFlow AI\n\n"
                    f"Forwarding to {destination} keeps failing:\n{e}\n\n"
                    "This usually means the account isn't admin there "
                    "(needs 'Post Messages' permission), or it isn't a "
                    "member of the chat. Open the project → 📤 Destinations "
                    "→ 🧪 Test to confirm, or check 📜 Logs for details."
                )

                return None

            backoff = RETRY_BACKOFF_BASE ** attempt

            log_service.add_log(
                project_id, "retry",
                f"Send to {destination} failed ({e}); retrying in {backoff}s"
            )
            stats_service.increment(project_id, "retried")

            await asyncio.sleep(backoff)

        except Exception as e:

            logger.exception("Unexpected error sending to %s", destination)

            log_service.add_log(
                project_id, "error",
                f"Unexpected error sending to {destination}: {e}"
            )
            stats_service.increment(project_id, "failed")

            await _alert_owner(
                project_id, destination,
                "⚠ ChannelFlow AI\n\n"
                f"An unexpected error is blocking forwarding to {destination}:\n{e}\n\n"
                "Check 📜 Logs on the project for details."
            )

            return None


# ==========================================
# DISPATCH
# ==========================================

async def _dispatch(messages, route):

    project_id = route["project_id"]
    settings = route["settings"]

    representative = messages[0]

    if not _passes_all_filters(representative, settings):
        stats_service.increment(project_id, "filtered")
        return

    delay_min = float(settings.get("delay_min") or 0)
    delay_max = float(settings.get("delay_max") or 0)

    if delay_max > 0:
        await asyncio.sleep(random.uniform(delay_min, delay_max))

    mode = settings.get("mode") or "forward"
    silent = bool(settings.get("silent"))
    protect_content = bool(settings.get("protect_content"))

    for destination in route["destinations"]:

        async def _send(destination=destination):

            if mode == "forward":

                # NOTE: client.forward_messages() does not accept
                # noforwards on every Telethon version - passing it
                # unconditionally used to raise a TypeError on EVERY
                # single send, which silently killed all forwarding
                # (it was caught by the generic except Exception below
                # and just logged/counted as "failed"). Try the fuller
                # call first, but never let an unsupported kwarg brick
                # forwarding again.
                try:
                    return await client.forward_messages(
                        destination,
                        messages,
                        silent=silent,
                        noforwards=protect_content,
                    )
                except TypeError:
                    return await client.forward_messages(
                        destination,
                        messages,
                        silent=silent,
                    )

            # copy mode: send new messages that don't carry the
            # "Forwarded from" tag.
            if len(messages) > 1:

                files = [m.media for m in messages if m.media]
                caption = next((m.raw_text for m in messages if m.raw_text), None)

                if files:
                    return await client.send_file(
                        destination,
                        files,
                        caption=caption,
                        silent=silent,
                        noforwards=protect_content,
                    )

            return await client.send_message(
                destination,
                representative,
                silent=silent,
                noforwards=protect_content,
            )

        result = await _send_with_retry(_send, project_id, destination)

        if result is not None:

            stats_service.increment(project_id, "forwarded")

            log_service.add_log(
                project_id, "forward",
                f"{representative.chat_id} -> {destination} "
                f"({len(messages)} message{'s' if len(messages) > 1 else ''})"
            )


# ==========================================
# ALBUM BUFFERING
# ==========================================

_album_buffers = {}  # (chat_id, grouped_id, project_id) -> {"messages": [...], "route": ..., "task": Task}


async def _flush_album(key):

    await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)

    buffered = _album_buffers.pop(key, None)

    if not buffered:
        return

    messages = sorted(buffered["messages"], key=lambda m: m.id)

    await _dispatch(messages, buffered["route"])


async def _handle_album_message(message, route):

    key = (message.chat_id, message.grouped_id, route["project_id"])

    if key not in _album_buffers:

        _album_buffers[key] = {
            "messages": [message],
            "route": route,
            "task": asyncio.create_task(_flush_album(key)),
        }

    else:
        _album_buffers[key]["messages"].append(message)


# ==========================================
# EVENT HANDLER
# ==========================================

@client.on(events.NewMessage)
async def forward_message(event):

    source_chat = str(event.chat_id)

    async with _routes_lock:
        routes = _ROUTES.get(source_chat)

    if not routes:
        return

    message = event.message

    for route in routes:

        keep_media_groups = bool(route["settings"].get("keep_media_groups"))

        if message.grouped_id and keep_media_groups:
            await _handle_album_message(message, route)
        else:
            asyncio.create_task(_dispatch([message], route))


# ==========================================
# START / RUN
# ==========================================

async def start_forwarder():

    await ensure_started()

    await _refresh_routes()

    refresh_task = asyncio.create_task(_routes_refresh_loop())

    logger.info("Forward Engine running")

    try:
        await client.run_until_disconnected()
    finally:
        refresh_task.cancel()


def run_forwarder():
    """
    Entry point run in a background thread by core.listener. Restarts
    itself with a backoff if the connection drops for a reason
    ``auto_reconnect`` couldn't fix on its own (e.g. the process's
    network came back after being fully offline).
    """

    delay = 5

    while True:

        try:
            asyncio.run(start_forwarder())
            # run_until_disconnected returned normally (clean disconnect
            # requested) - don't spin-loop restarting it.
            break

        except Exception:
            logger.exception(
                "Forward engine crashed; restarting in %ss", delay
            )
            time.sleep(delay)
            delay = min(delay * 2, 60)
