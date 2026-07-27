import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from config import BOT_TOKEN

from database.db import init_db

from bot.handlers import (
    start,
    cancel,
    admin_panel,
    menu_handler,
    button_handler
)

from core.listener import start_listener, stop_listener
from core.client import client as telethon_client
from bot import notifier


# ==========================================
# LOGGING
# ==========================================

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)

# python-telegram-bot's own HTTP client is chatty at INFO; keep it at
# WARNING so real application logs aren't drowned out.
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger("channelflow")


# ==========================================
# DATABASE
# ==========================================

init_db()

logger.info("Database initialized")


# ==========================================
# GLOBAL ERROR HANDLER
# ==========================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):

    logger.error("Unhandled exception while processing an update", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:

        try:
            await update.effective_message.reply_text(
                "⚠ Something went wrong. Please try again."
            )
        except Exception:
            pass


# ==========================================
# START FORWARD ENGINE
# (scheduled on the bot's own event loop via
# post_init - see core/listener.py for why this
# replaced the old separate-thread approach)
# ==========================================

async def _post_init(app: Application) -> None:
    notifier.set_bot(app.bot)
    start_listener()


async def _post_shutdown(app: Application) -> None:
    await stop_listener()

    if telethon_client.is_connected():
        await telethon_client.disconnect()


# ==========================================
# BOT
# ==========================================

app = (
    Application.builder()
    .token(BOT_TOKEN)
    .post_init(_post_init)
    .post_shutdown(_post_shutdown)
    .build()
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("cancel", cancel))
app.add_handler(CommandHandler("admin", admin_panel))

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        menu_handler
    )
)

app.add_handler(CallbackQueryHandler(button_handler))

app.add_error_handler(error_handler)

logger.info("ChannelFlow AI bot starting...")

app.run_polling(allowed_updates=Update.ALL_TYPES)
