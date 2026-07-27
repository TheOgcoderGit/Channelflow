"""
Forward-engine lifecycle.

Runs as a plain ``asyncio.Task`` on the *same* event loop as the
Telegram bot (python-telegram-bot), scheduled from ``main.py``'s
``post_init`` hook.

Why this matters
-----------------
An earlier version of this file started the forward engine on a
separate OS thread, with its own ``asyncio.run(...)`` (its own event
loop). Forwarding itself worked fine there, but the shared Telethon
``client`` (``core.client.client``) got connected/authorized on that
thread's loop. Any on-demand Telethon call made from the *bot's* loop
(e.g. resolving a channel via ``get_chat`` when adding a source or
destination) was then reaching into a client bound to a different loop,
which hangs or fails silently - Telethon clients are not safe to drive
from two event loops at once. That was the "sources/destinations won't
add" bug: forwarding kept working, on-demand lookups from the bot did
not.

The fix is architectural, not a patch: there is only one event loop in
the whole process now, so there's nothing to bridge.
"""
import asyncio
import logging
from typing import Optional

from core.forwarder import start_forwarder
from bot import notifier

logger = logging.getLogger(__name__)

_forward_task: Optional[asyncio.Task] = None

_INITIAL_BACKOFF = 5
_MAX_BACKOFF = 60


async def _run_forever() -> None:
    """Async equivalent of the old thread's restart-with-backoff loop."""

    delay = _INITIAL_BACKOFF

    while True:
        try:
            await start_forwarder()
            # run_until_disconnected() returned normally (a clean,
            # intentional disconnect) - don't spin-loop restarting it.
            break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(
                "Forward engine crashed; restarting in %ss", delay
            )

            hint = (
                "The Telethon session isn't authorized. Run "
                "`python -m core.authorize` on the server once, then "
                "restart the bot."
                if isinstance(e, RuntimeError) and "not authorized" in str(e).lower()
                else str(e)
            )

            await notifier.notify_admins(
                "🔴 ChannelFlow AI\n\n"
                "The forward engine crashed and is retrying in the "
                f"background:\n{hint}\n\n"
                "No messages will forward until this is resolved.",
                throttle_key="engine_crash",
            )

            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_BACKOFF)


def start_listener() -> None:
    """
    Schedules the forward engine as a background task on the CURRENT
    event loop. Must be called from within a running event loop (see
    ``main.py``'s ``post_init`` hook) so it shares that loop with
    everything else, including the bot handlers.
    """

    global _forward_task

    if _forward_task is not None and not _forward_task.done():
        logger.info("Forward Engine Already Running")
        return

    _forward_task = asyncio.create_task(_run_forever())

    logger.info("==============================")
    logger.info("Listener Started")
    logger.info("==============================")


async def stop_listener() -> None:
    """Cancels the forward engine task cleanly (used on shutdown)."""

    global _forward_task

    if _forward_task is None:
        return

    _forward_task.cancel()

    try:
        await _forward_task
    except (asyncio.CancelledError, Exception):
        pass

    _forward_task = None


def is_running() -> bool:
    return _forward_task is not None and not _forward_task.done()
