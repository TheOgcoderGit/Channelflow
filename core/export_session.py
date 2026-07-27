"""
ChannelFlow AI - Export Session As A String
==============================================

Run this ONCE, LOCALLY, after you've already logged in with
``python -m core.authorize`` (i.e. ``<SESSION_NAME>.session`` exists and
is authorized):

    python -m core.export_session

It prints a single string that represents your login. Paste that string
into your host's environment variables as ``SESSION_STRING`` (Render,
Railway, Heroku, ...).

Why this exists
----------------
Most PaaS hosts wipe the local filesystem on every redeploy unless you
pay for a persistent disk. Without this, that would mean re-running the
full interactive phone/OTP login every time you push a change - not
practical on a server with no interactive terminal anyway. With
SESSION_STRING set, ``core/client.py`` authorizes straight from the
string, so the account stays logged in across redeploys/restarts with
no disk needed just for auth.

This string is equivalent to your Telegram login - treat it exactly
like a password. Only ever put it in your host's secret/environment
variable storage, never in code, git, or chat.
"""

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import API_ID, API_HASH, SESSION_NAME


async def _export():

    # Deliberately uses the plain file-based session here (not
    # core.client.client), since the whole point is reading the
    # existing <SESSION_NAME>.session file regardless of whether
    # SESSION_STRING happens to already be set in this shell.
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    await client.connect()

    if not await client.is_user_authorized():
        print(
            "This session isn't authorized yet.\n"
            "Run `python -m core.authorize` first, then re-run this script."
        )
        await client.disconnect()
        return

    me = await client.get_me()
    string_session = StringSession.save(client.session)

    print("================================================")
    print(f"Logged in as {me.first_name} (@{me.username})")
    print("================================================")
    print()
    print("SESSION_STRING (copy everything on the next line):")
    print()
    print(string_session)
    print()
    print("Set this as SESSION_STRING in your host's environment")
    print("variables. Keep it secret - it's equivalent to your login.")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(_export())
