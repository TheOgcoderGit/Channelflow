import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID_RAW = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "ChannelFlow")

# Optional: a Telethon StringSession (see core/export_session.py). When
# set, the account stays logged in without needing a local .session file
# at all - useful on hosts like Render where the filesystem is wiped on
# every redeploy unless you pay for a persistent disk.
SESSION_STRING = os.getenv("SESSION_STRING", "").strip() or None

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Add it to your .env file.")

if not API_ID_RAW:
    raise RuntimeError("API_ID is not set. Add it to your .env file.")

if not API_HASH:
    raise RuntimeError("API_HASH is not set. Add it to your .env file.")

try:
    API_ID = int(API_ID_RAW)
except ValueError:
    raise RuntimeError("API_ID must be a numeric Telegram API id.")

# Comma-separated list of Telegram user ids allowed to use /admin,
# e.g. ADMIN_IDS=123456789,987654321
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
