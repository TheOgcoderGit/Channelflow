"""
ChannelFlow AI - Telegram Bot Handlers
========================================

This module contains every user-facing handler for the bot:

    * /start                       -> start()
    * /cancel                      -> cancel()
    * Reply keyboard (main menu)   -> menu_handler()
    * Inline keyboard callbacks    -> button_handler()

Design notes
------------
State is tracked with the plain module-level dictionaries defined in
``bot.states`` (WAITING_PROJECT_NAME, WAITING_SOURCE, WAITING_DESTINATION,
WAITING_RENAME, CURRENT_PROJECT), keyed by the Telegram user id. This keeps
the handlers compatible with the rest of the project's architecture.

Every callback_data string consumed here matches exactly what is produced
by ``bot.keyboards`` (project_keyboard, source_item_keyboard,
destination_item_keyboard, settings_keyboard). No callback name was
invented that isn't already wired into a keyboard.

Ownership of every project / source / destination is verified against the
requesting Telegram user before any read or write happens, closing the
insecure-direct-object-reference gap that existed in the previous
implementation (any user could act on any project by guessing/crafting a
project_id in callback data).
"""

import logging

from telegram import Update, CallbackQuery
from telegram.ext import ContextTypes

from bot.keyboards import (
    main_menu,
    project_keyboard,
    source_item_keyboard,
    destination_item_keyboard,
    settings_keyboard,
    admin_keyboard,
    project_settings_keyboard,
    project_filters_keyboard,
    media_filter_choice_keyboard,
)

from bot.states import (
    WAITING_PROJECT_NAME,
    WAITING_SOURCE,
    WAITING_DESTINATION,
    WAITING_RENAME,
    WAITING_DELAY,
    WAITING_WHITELIST,
    WAITING_BLACKLIST,
    WAITING_REGEX,
    WAITING_BROADCAST,
    CURRENT_PROJECT
)

from database.models import register_user, get_all_user_ids, count_users
from config import ADMIN_IDS

from services.project_service import (
    create_project,
    get_projects,
    get_project,
    rename_project,
    delete_project,
    update_status,
    count_projects
)

from services.source_service import (
    add_source,
    get_sources,
    get_source,
    delete_source,
    count_sources,
    toggle_source_enabled
)

from services.destination_service import (
    add_destination,
    get_destinations,
    get_destination,
    delete_destination,
    count_destinations,
    toggle_destination_enabled
)

from services import settings_service, log_service, stats_service

from core.telegram_utils import get_chat, send_test_message
from core.listener import is_running
from core.forwarder import force_refresh_routes


logger = logging.getLogger(__name__)


# ==========================================
# CONSTANTS
# ==========================================

BTN_NEW_PROJECT = "➕ New Project"
BTN_MY_PROJECTS = "📁 My Projects"
BTN_STATUS = "📊 Status"
BTN_SETTINGS = "⚙ Settings"

MAIN_MENU_BUTTONS = {
    BTN_NEW_PROJECT,
    BTN_MY_PROJECTS,
    BTN_STATUS,
    BTN_SETTINGS
}

MAX_NAME_LENGTH = 100


# ==========================================
# STATE HELPERS
# ==========================================

def _reset_waiting_states(user_id):
    """
    Clears every pending input flow for a user. Called whenever the user
    navigates away (menu button, cancel, project deletion, errors) so a
    stale waiting flag never swallows an unrelated future message.
    """

    WAITING_PROJECT_NAME.pop(user_id, None)
    WAITING_SOURCE.pop(user_id, None)
    WAITING_DESTINATION.pop(user_id, None)
    WAITING_RENAME.pop(user_id, None)
    WAITING_DELAY.pop(user_id, None)
    WAITING_WHITELIST.pop(user_id, None)
    WAITING_BLACKLIST.pop(user_id, None)
    WAITING_REGEX.pop(user_id, None)
    WAITING_BROADCAST.pop(user_id, None)


def _get_owned_project(project_id, user_id):
    """
    Returns the project row if it exists AND belongs to user_id,
    otherwise None. Prevents cross-account access via crafted callback
    data.
    """

    project = get_project(project_id)

    if project is None:
        return None

    if project["user_id"] != user_id:
        return None

    return project


def _get_owned_source(source_id, user_id):
    """
    Returns (source, project) if the source exists and its parent
    project belongs to user_id, otherwise (None, None).
    """

    source = get_source(source_id)

    if source is None:
        return None, None

    project = _get_owned_project(source["project_id"], user_id)

    if project is None:
        return None, None

    return source, project


def _get_owned_destination(destination_id, user_id):
    """
    Returns (destination, project) if the destination exists and its
    parent project belongs to user_id, otherwise (None, None).
    """

    destination = get_destination(destination_id)

    if destination is None:
        return None, None

    project = _get_owned_project(destination["project_id"], user_id)

    if project is None:
        return None, None

    return destination, project


# ==========================================
# FORMATTING HELPERS
# ==========================================

def _project_status_text(project):
    return "🟢 Running" if project["status"] else "🔴 Stopped"


def _project_card_text(project):

    sources_total = count_sources(project["id"])
    destinations_total = count_destinations(project["id"])

    return (
        f"📂 {project['name']}\n\n"
        f"{_project_status_text(project)}\n\n"
        f"📥 Sources: {sources_total}\n"
        f"📤 Destinations: {destinations_total}"
    )


def _source_card_text(source):

    username = source["username"] or "-"
    chat_type = source["chat_type"] or "Unknown"
    state = "🟢 Enabled" if source["enabled"] else "🔴 Disabled"

    return (
        "📥 Source\n\n"
        f"📂 {source['title'] or '-'}\n"
        f"🏷 {chat_type}\n"
        f"👤 @{username}\n"
        f"🆔 {source['chat_id']}\n"
        f"{state}"
    )


def _destination_card_text(destination):

    username = destination["username"] or "-"
    chat_type = destination["chat_type"] or "Unknown"
    state = "🟢 Enabled" if destination["enabled"] else "🔴 Disabled"

    return (
        "📤 Destination\n\n"
        f"📂 {destination['title'] or '-'}\n"
        f"🏷 {chat_type}\n"
        f"👤 @{username}\n"
        f"🆔 {destination['chat_id']}\n"
        f"{state}"
    )


# ==========================================
# /start
# ==========================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    register_user(
        user.id,
        user.username,
        user.first_name
    )

    _reset_waiting_states(user.id)

    if context.bot_data.get("maintenance_mode") and user.id not in ADMIN_IDS:

        await update.message.reply_text(
            "🔧 ChannelFlow AI is under maintenance right now. "
            "Please try again shortly."
        )

        return

    await update.message.reply_text(

        f"👋 Welcome {user.first_name}\n\n"
        "🤖 ChannelFlow AI\n\n"
        "Professional Telegram Auto Forward Bot\n\n"
        "Use the menu below to create your first project.",

        reply_markup=main_menu

    )


# ==========================================
# /admin
# ==========================================

def _admin_dashboard_text(context=None):

    total_users = count_users()
    engine_state = "🟢 Online" if is_running() else "🔴 Offline"
    maintenance = False

    if context is not None:
        maintenance = context.bot_data.get("maintenance_mode", False)

    return (
        "🛠 Admin Dashboard\n\n"
        f"👥 Users: {total_users}\n"
        f"🚀 Forward Engine: {engine_state}\n"
        f"🔧 Maintenance Mode: {'On' if maintenance else 'Off'}"
    )


async def admin_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admins only.")
        return

    await update.message.reply_text(
        _admin_dashboard_text(context),
        reply_markup=admin_keyboard
    )


# ==========================================
# /cancel
# ==========================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    had_state = (
        user.id in WAITING_PROJECT_NAME
        or user.id in WAITING_SOURCE
        or user.id in WAITING_DESTINATION
        or user.id in WAITING_RENAME
    )

    _reset_waiting_states(user.id)

    if had_state:

        await update.message.reply_text(
            "❌ Cancelled\n\n"
            "The pending action was cancelled.",
            reply_markup=main_menu
        )

    else:

        await update.message.reply_text(
            "ℹ Nothing to cancel.",
            reply_markup=main_menu
        )


# ==========================================
# MAIN MENU (REPLY KEYBOARD) HANDLER
# ==========================================

async def menu_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    message = update.message

    if message is None or not message.text:
        return

    text = message.text.strip()

    register_user(
        user.id,
        user.username,
        user.first_name
    )

    # ======================================
    # MAIN MENU NAVIGATION
    # (always takes priority and clears any
    # pending waiting-state so the user can
    # never get permanently stuck)
    # ======================================

    if text in MAIN_MENU_BUTTONS:

        _reset_waiting_states(user.id)

        if text == BTN_NEW_PROJECT:

            WAITING_PROJECT_NAME[user.id] = True

            await message.reply_text(
                "📝 Send Project Name"
            )

            return

        if text == BTN_MY_PROJECTS:
            await _send_my_projects(message, user.id)
            return

        if text == BTN_STATUS:
            await _send_status(message, user.id)
            return

        if text == BTN_SETTINGS:

            await message.reply_text(
                "⚙ ChannelFlow Settings",
                reply_markup=settings_keyboard
            )

            return

    # ======================================
    # CREATE PROJECT
    # ======================================

    if user.id in WAITING_PROJECT_NAME:
        await _handle_create_project(message, user.id, text)
        return

    # ======================================
    # RENAME PROJECT
    # ======================================

    if user.id in WAITING_RENAME:
        await _handle_rename_project(message, user.id, text)
        return

    # ======================================
    # ADD SOURCE
    # ======================================

    if user.id in WAITING_SOURCE:
        await _handle_add_source(message, user.id, text)
        return

    # ======================================
    # ADD DESTINATION
    # ======================================

    if user.id in WAITING_DESTINATION:
        await _handle_add_destination(message, user.id, text)
        return

    # ======================================
    # SET DELAY
    # ======================================

    if user.id in WAITING_DELAY:
        await _handle_set_delay(message, user.id, text)
        return

    # ======================================
    # SET WHITELIST
    # ======================================

    if user.id in WAITING_WHITELIST:
        await _handle_set_whitelist(message, user.id, text)
        return

    # ======================================
    # SET BLACKLIST
    # ======================================

    if user.id in WAITING_BLACKLIST:
        await _handle_set_blacklist(message, user.id, text)
        return

    # ======================================
    # SET REGEX
    # ======================================

    if user.id in WAITING_REGEX:
        await _handle_set_regex(message, user.id, text)
        return

    # ======================================
    # ADMIN BROADCAST
    # ======================================

    if user.id in WAITING_BROADCAST and user.id in ADMIN_IDS:
        await _handle_broadcast(message, context, user.id, text)
        return

    # ======================================
    # FALLBACK
    # ======================================

    await message.reply_text(
        "❓ I didn't understand that.\n\n"
        "Please use the menu below.",
        reply_markup=main_menu
    )


# ==========================================
# MENU BRANCH IMPLEMENTATIONS
# ==========================================

async def _send_my_projects(message, user_id):

    projects = get_projects(user_id)

    if not projects:

        await message.reply_text(
            "❌ No Projects Found\n\n"
            "Tap ➕ New Project to create one."
        )

        return

    for project in projects:

        await message.reply_text(
            _project_card_text(project),
            reply_markup=project_keyboard(project["id"], running=bool(project["status"]))
        )


async def _send_status(message, user_id):

    projects = get_projects(user_id)

    total = count_projects(user_id)
    running = sum(1 for project in projects if project["status"])

    engine_state = "🟢 Online" if is_running() else "🔴 Offline"

    await message.reply_text(

        "📊 ChannelFlow AI\n\n"
        f"📁 Projects : {total}\n"
        f"▶ Running : {running}\n"
        f"⏹ Stopped : {total - running}\n\n"
        f"⚙ Forward Engine : {engine_state}"

    )


async def _handle_create_project(message, user_id, text):

    if not text:

        await message.reply_text(
            "❌ Project name cannot be empty. Send a valid name."
        )

        return

    if len(text) > MAX_NAME_LENGTH:

        await message.reply_text(
            f"❌ Project name is too long (max {MAX_NAME_LENGTH} characters)."
        )

        return

    project_id = create_project(user_id, text)

    CURRENT_PROJECT[user_id] = project_id

    WAITING_PROJECT_NAME.pop(user_id, None)

    project = get_project(project_id)

    await message.reply_text(

        "✅ Project Created\n\n"
        f"📂 {project['name']}",

        reply_markup=project_keyboard(project_id)

    )


async def _handle_rename_project(message, user_id, text):

    project_id = CURRENT_PROJECT.get(user_id)
    project = _get_owned_project(project_id, user_id) if project_id else None

    if project is None:

        WAITING_RENAME.pop(user_id, None)

        await message.reply_text(
            "❌ No project selected. Open a project and tap ✏ Rename again.",
            reply_markup=main_menu
        )

        return

    if not text:

        await message.reply_text(
            "❌ Project name cannot be empty. Send a valid name."
        )

        return

    if len(text) > MAX_NAME_LENGTH:

        await message.reply_text(
            f"❌ Project name is too long (max {MAX_NAME_LENGTH} characters)."
        )

        return

    rename_project(project_id, text)

    WAITING_RENAME.pop(user_id, None)

    project = get_project(project_id)

    await message.reply_text(

        "✅ Project Renamed\n\n"
        f"📂 {project['name']}",

        reply_markup=project_keyboard(project_id)

    )


async def _handle_add_source(message, user_id, text):

    project_id = CURRENT_PROJECT.get(user_id)
    project = _get_owned_project(project_id, user_id) if project_id else None

    if project is None:

        WAITING_SOURCE.pop(user_id, None)

        await message.reply_text(
            "❌ No project selected. Open a project and tap ➕ Source again.",
            reply_markup=main_menu
        )

        return

    try:
        chat = await get_chat(text)
    except Exception as e:
        logger.exception("get_chat failed while adding source: %s", e)
        await message.reply_text(f"❌ Couldn't add this source\n\n{e}")
        return

    if chat is None:

        await message.reply_text(
            "❌ Invalid Channel / Group / Bot\n\n"
            "Send a valid public username, e.g. @YourChannel"
        )

        return

    ok = add_source(
        project_id,
        chat["chat_id"],
        chat["username"],
        chat["title"],
        chat["type"]
    )

    WAITING_SOURCE.pop(user_id, None)

    if ok:

        await force_refresh_routes()

        text = (
            "✅ Source Added\n\n"
            f"📂 {chat['title'] or chat['username'] or chat['chat_id']}\n"
            f"🏷 {chat['type']}"
        )

        if not chat.get("joined", True):
            text += f"\n\n⚠ {chat['join_note']}"

        await message.reply_text(
            text,
            reply_markup=project_keyboard(project_id)
        )

    else:

        await message.reply_text(
            "⚠ Source Already Exists",
            reply_markup=project_keyboard(project_id)
        )


async def _handle_add_destination(message, user_id, text):

    project_id = CURRENT_PROJECT.get(user_id)
    project = _get_owned_project(project_id, user_id) if project_id else None

    if project is None:

        WAITING_DESTINATION.pop(user_id, None)

        await message.reply_text(
            "❌ No project selected. Open a project and tap ➕ Destination again.",
            reply_markup=main_menu
        )

        return

    try:
        chat = await get_chat(text, for_destination=True)
    except Exception as e:
        logger.exception("get_chat failed while adding destination: %s", e)
        await message.reply_text(f"❌ Couldn't add this destination\n\n{e}")
        return

    if chat is None:

        await message.reply_text(
            "❌ Invalid Channel / Group / Bot\n\n"
            "Send a valid public username, e.g. @YourChannel"
        )

        return

    ok = add_destination(
        project_id,
        chat["chat_id"],
        chat["username"],
        chat["title"],
        chat["type"]
    )

    WAITING_DESTINATION.pop(user_id, None)

    if ok:

        await force_refresh_routes()

        text = (
            "✅ Destination Added\n\n"
            f"📂 {chat['title'] or chat['username'] or chat['chat_id']}\n"
            f"🏷 {chat['type']}"
        )

        if not chat.get("joined", True):
            text += f"\n\n⚠ {chat['join_note']}"

        await message.reply_text(
            text,
            reply_markup=project_keyboard(project_id)
        )

    else:

        await message.reply_text(
            "⚠ Destination Already Exists",
            reply_markup=project_keyboard(project_id)
        )


# ==========================================
# PROJECT SETTINGS TEXT-INPUT HANDLERS
# ==========================================

async def _handle_set_delay(message, user_id, text):

    project_id = CURRENT_PROJECT.get(user_id)
    project = _get_owned_project(project_id, user_id) if project_id else None

    if project is None:

        WAITING_DELAY.pop(user_id, None)

        await message.reply_text(
            "❌ No project selected.",
            reply_markup=main_menu
        )

        return

    WAITING_DELAY.pop(user_id, None)

    parts = [p.strip() for p in text.replace(" ", "").split(",")]

    try:

        if len(parts) == 1:
            delay_min = delay_max = float(parts[0])
        else:
            delay_min, delay_max = float(parts[0]), float(parts[1])

        if delay_min < 0 or delay_max < 0:
            raise ValueError

    except (ValueError, IndexError):

        await message.reply_text(
            "❌ Invalid format. Send a single number (fixed delay) or "
            "two numbers separated by a comma (random range), e.g.\n\n"
            "5\n\nor\n\n2,8"
        )

        return

    settings_service.set_delay(project_id, delay_min, delay_max)
    await force_refresh_routes()

    settings = settings_service.get_settings(project_id)

    await message.reply_text(
        "✅ Delay Updated",
        reply_markup=project_settings_keyboard(project_id, settings)
    )


async def _handle_set_whitelist(message, user_id, text):

    project_id = CURRENT_PROJECT.get(user_id)
    project = _get_owned_project(project_id, user_id) if project_id else None

    if project is None:
        WAITING_WHITELIST.pop(user_id, None)
        await message.reply_text("❌ No project selected.", reply_markup=main_menu)
        return

    WAITING_WHITELIST.pop(user_id, None)

    value = "" if text.strip() == "-" else text.strip()
    settings_service.set_keyword_whitelist(project_id, value)
    await force_refresh_routes()

    settings = settings_service.get_settings(project_id)

    await message.reply_text(
        "✅ Whitelist Updated" if value else "✅ Whitelist Cleared",
        reply_markup=project_filters_keyboard(project_id, settings)
    )


async def _handle_set_blacklist(message, user_id, text):

    project_id = CURRENT_PROJECT.get(user_id)
    project = _get_owned_project(project_id, user_id) if project_id else None

    if project is None:
        WAITING_BLACKLIST.pop(user_id, None)
        await message.reply_text("❌ No project selected.", reply_markup=main_menu)
        return

    WAITING_BLACKLIST.pop(user_id, None)

    value = "" if text.strip() == "-" else text.strip()
    settings_service.set_keyword_blacklist(project_id, value)
    await force_refresh_routes()

    settings = settings_service.get_settings(project_id)

    await message.reply_text(
        "✅ Blacklist Updated" if value else "✅ Blacklist Cleared",
        reply_markup=project_filters_keyboard(project_id, settings)
    )


async def _handle_set_regex(message, user_id, text):

    project_id = CURRENT_PROJECT.get(user_id)
    project = _get_owned_project(project_id, user_id) if project_id else None

    if project is None:
        WAITING_REGEX.pop(user_id, None)
        await message.reply_text("❌ No project selected.", reply_markup=main_menu)
        return

    WAITING_REGEX.pop(user_id, None)

    value = "" if text.strip() == "-" else text.strip()

    if value:

        import re as _re

        try:
            _re.compile(value)
        except _re.error as e:

            await message.reply_text(
                f"❌ Invalid regex: {e}\n\nSend a valid pattern, or `-` to clear."
            )

            return

    settings_service.set_regex_filter(project_id, value)
    await force_refresh_routes()

    settings = settings_service.get_settings(project_id)

    await message.reply_text(
        "✅ Regex Filter Updated" if value else "✅ Regex Filter Cleared",
        reply_markup=project_filters_keyboard(project_id, settings)
    )


async def _handle_broadcast(message, context, admin_id, text):

    WAITING_BROADCAST.pop(admin_id, None)

    user_ids = get_all_user_ids()

    sent = 0
    failed = 0

    for uid in user_ids:

        try:
            await context.bot.send_message(uid, f"📢 Announcement\n\n{text}")
            sent += 1
        except Exception:
            failed += 1

    await message.reply_text(
        f"✅ Broadcast Complete\n\nDelivered: {sent}\nFailed: {failed}"
    )


# ==========================================
# INLINE KEYBOARD (CALLBACK) HANDLER
# ==========================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query: CallbackQuery = update.callback_query

    await query.answer()

    data = query.data or ""
    user_id = query.from_user.id

    parts = data.split(":")
    action = parts[0]

    try:

        # ======================================
        # ADD SOURCE
        # ======================================

        if action == "source":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            _reset_waiting_states(user_id)

            CURRENT_PROJECT[user_id] = project_id
            WAITING_SOURCE[user_id] = True

            await query.message.reply_text(
                "📥 Send Source Username\n\n"
                "Example:\n"
                "@YourChannel"
            )

            return

        # ======================================
        # ADD DESTINATION
        # ======================================

        if action == "destination":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            _reset_waiting_states(user_id)

            CURRENT_PROJECT[user_id] = project_id
            WAITING_DESTINATION[user_id] = True

            await query.message.reply_text(
                "📤 Send Destination Username\n\n"
                "Example:\n"
                "@YourChannel"
            )

            return

        # ======================================
        # LIST SOURCES
        # ======================================

        if action == "listsource":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            sources = get_sources(project_id)

            if not sources:

                await query.message.reply_text(
                    "❌ No Sources Added\n\n"
                    "Tap ➕ Source on the project dashboard to add one."
                )

                return

            for source in sources:

                await query.message.reply_text(
                    _source_card_text(source),
                    reply_markup=source_item_keyboard(
                        source["id"], project_id, bool(source["enabled"])
                    )
                )

            return

        # ======================================
        # LIST DESTINATIONS
        # ======================================

        if action == "listdestination":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            destinations = get_destinations(project_id)

            if not destinations:

                await query.message.reply_text(
                    "❌ No Destinations Added\n\n"
                    "Tap ➕ Destination on the project dashboard to add one."
                )

                return

            for destination in destinations:

                await query.message.reply_text(
                    _destination_card_text(destination),
                    reply_markup=destination_item_keyboard(
                        destination["id"], project_id, bool(destination["enabled"])
                    )
                )

            return

        # ======================================
        # START PROJECT
        # ======================================

        if action == "start":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            if count_sources(project_id) == 0:

                await query.message.reply_text(
                    "⚠ Cannot Start\n\n"
                    "Add at least one source before starting."
                )

                return

            if count_destinations(project_id) == 0:

                await query.message.reply_text(
                    "⚠ Cannot Start\n\n"
                    "Add at least one destination before starting."
                )

                return

            update_status(project_id, 1)
            await force_refresh_routes()

            project = get_project(project_id)

            await query.message.reply_text(

                "🟢 Project Started\n\n"
                f"📂 {project['name']}",

                reply_markup=project_keyboard(project_id, running=True)

            )

            return

        # ======================================
        # STOP PROJECT
        # ======================================

        if action == "stop":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            update_status(project_id, 0)
            await force_refresh_routes()

            project = get_project(project_id)

            await query.message.reply_text(

                "🔴 Project Stopped\n\n"
                f"📂 {project['name']}",

                reply_markup=project_keyboard(project_id, running=False)

            )

            return

        # ======================================
        # DELETE SOURCE
        # ======================================

        if action == "deletesource":

            source_id = int(parts[1])

            source, project = _get_owned_source(source_id, user_id)

            if source is None:

                await query.message.reply_text("❌ Source Not Found")
                return

            delete_source(source_id)
            await force_refresh_routes()

            await query.message.reply_text(

                "✅ Source Deleted\n\n"
                f"📂 {source['title'] or source['chat_id']}",

                reply_markup=project_keyboard(project["id"])

            )

            return

        # ======================================
        # DELETE DESTINATION
        # ======================================

        if action == "deletedestination":

            destination_id = int(parts[1])

            destination, project = _get_owned_destination(destination_id, user_id)

            if destination is None:

                await query.message.reply_text("❌ Destination Not Found")
                return

            delete_destination(destination_id)
            await force_refresh_routes()

            await query.message.reply_text(

                "✅ Destination Deleted\n\n"
                f"📂 {destination['title'] or destination['chat_id']}",

                reply_markup=project_keyboard(project["id"])

            )

            return

        # ======================================
        # TEST DESTINATION
        # ======================================

        if action == "testdestination":

            destination_id = int(parts[1])

            destination, project = _get_owned_destination(destination_id, user_id)

            if destination is None:
                await query.message.reply_text("❌ Destination Not Found")
                return

            await query.message.reply_text("🧪 Sending a real test message...")

            ok, detail = await send_test_message(destination["chat_id"], project["name"])

            label = destination["title"] or destination["username"] or destination["chat_id"]

            if ok:
                await query.message.reply_text(f"✅ Test Passed\n\n📤 {label} - message delivered.")
            else:
                await query.message.reply_text(f"❌ Test Failed\n\n📤 {label}\n\n{detail}")

            return

        # ======================================
        # TEST ALL DESTINATIONS FOR A PROJECT
        # ======================================

        if action == "testproject":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            destinations = get_destinations(project_id)

            if not destinations:
                await query.message.reply_text(
                    "❌ No Destinations Added\n\n"
                    "Tap ➕ Destination on the project dashboard to add one."
                )
                return

            await query.message.reply_text(
                f"🧪 Testing {len(destinations)} destination(s)..."
            )

            lines = []

            for destination in destinations:

                ok, detail = await send_test_message(destination["chat_id"], project["name"])
                label = destination["title"] or destination["username"] or destination["chat_id"]

                lines.append(
                    f"✅ {label}" if ok else f"❌ {label} - {detail}"
                )

            await query.message.reply_text(
                "🧪 Test Results\n\n" + "\n".join(lines)
            )

            return

        # ======================================
        # RENAME PROJECT
        # ======================================

        if action == "rename":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            _reset_waiting_states(user_id)

            CURRENT_PROJECT[user_id] = project_id
            WAITING_RENAME[user_id] = True

            await query.message.reply_text(
                "✏ Send New Project Name"
            )

            return

        # ======================================
        # DELETE PROJECT
        # ======================================

        if action == "delete":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            delete_project(project_id)
            await force_refresh_routes()

            if CURRENT_PROJECT.get(user_id) == project_id:
                _reset_waiting_states(user_id)
                CURRENT_PROJECT.pop(user_id, None)

            await query.message.reply_text(
                "🗑 Project Deleted Successfully\n\n"
                f"📂 {project['name']}"
            )

            return

        # ======================================
        # SETTINGS
        # ======================================

        if action == "settings":

            sub_action = parts[1] if len(parts) > 1 else ""

            if sub_action == "refresh":

                total = count_projects(user_id)
                projects = get_projects(user_id)
                running = sum(1 for project in projects if project["status"])
                engine_state = "🟢 Online" if is_running() else "🔴 Offline"

                try:

                    await query.edit_message_text(

                        "⚙ ChannelFlow Settings\n\n"
                        f"📁 Projects : {total}\n"
                        f"▶ Running : {running}\n"
                        f"⏹ Stopped : {total - running}\n\n"
                        f"🚀 Forward Engine : {engine_state}\n"
                        "📡 Mode : Native Forward",

                        reply_markup=settings_keyboard

                    )

                except Exception:
                    # message content/markup unchanged - safe to ignore
                    pass

                return

            await query.message.reply_text("⚠ Unknown Settings Action")
            return

        # ======================================
        # TOGGLE SOURCE ENABLED
        # ======================================

        if action == "togglesource":

            source_id = int(parts[1])
            source, project = _get_owned_source(source_id, user_id)

            if source is None:
                await query.message.reply_text("❌ Source Not Found")
                return

            new_value = toggle_source_enabled(source_id)
            await force_refresh_routes()
            source = get_source(source_id)

            await query.message.edit_text(
                _source_card_text(source),
                reply_markup=source_item_keyboard(source_id, project["id"], bool(new_value))
            )

            return

        # ======================================
        # TOGGLE DESTINATION ENABLED
        # ======================================

        if action == "toggledestination":

            destination_id = int(parts[1])
            destination, project = _get_owned_destination(destination_id, user_id)

            if destination is None:
                await query.message.reply_text("❌ Destination Not Found")
                return

            new_value = toggle_destination_enabled(destination_id)
            await force_refresh_routes()
            destination = get_destination(destination_id)

            await query.message.edit_text(
                _destination_card_text(destination),
                reply_markup=destination_item_keyboard(
                    destination_id, project["id"], bool(new_value)
                )
            )

            return

        # ======================================
        # BACK TO PROJECT DASHBOARD
        # ======================================

        if action == "backproject":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            await query.message.edit_text(
                _project_card_text(project),
                reply_markup=project_keyboard(project_id)
            )

            return

        # ======================================
        # PROJECT FORWARD SETTINGS
        # ======================================

        if action == "projsettings":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            CURRENT_PROJECT[user_id] = project_id
            settings = settings_service.get_settings(project_id)

            await query.message.reply_text(
                f"⚙ Forward Settings\n\n📂 {project['name']}",
                reply_markup=project_settings_keyboard(project_id, settings)
            )

            return

        if action == "togglemode":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            settings_service.toggle_mode(project_id)
            await force_refresh_routes()
            settings = settings_service.get_settings(project_id)

            await query.message.edit_reply_markup(
                reply_markup=project_settings_keyboard(project_id, settings)
            )

            return

        if action in ("togglesilent", "toggleprotect", "togglealbum"):

            field_map = {
                "togglesilent": "silent",
                "toggleprotect": "protect_content",
                "togglealbum": "keep_media_groups",
            }

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            settings_service.toggle_flag(project_id, field_map[action])
            await force_refresh_routes()
            settings = settings_service.get_settings(project_id)

            await query.message.edit_reply_markup(
                reply_markup=project_settings_keyboard(project_id, settings)
            )

            return

        if action == "setdelay":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            _reset_waiting_states(user_id)
            CURRENT_PROJECT[user_id] = project_id
            WAITING_DELAY[user_id] = True

            await query.message.reply_text(
                "⏱ Send Delay\n\n"
                "Single number for a fixed delay (seconds), e.g. `5`\n"
                "Two numbers for a random range, e.g. `2,8`"
            )

            return

        # ======================================
        # PROJECT FILTER SETTINGS
        # ======================================

        if action == "projfilters":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            CURRENT_PROJECT[user_id] = project_id
            settings = settings_service.get_settings(project_id)

            await query.message.reply_text(
                f"🧹 Filters\n\n📂 {project['name']}",
                reply_markup=project_filters_keyboard(project_id, settings)
            )

            return

        if action == "mediafilter":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            await query.message.edit_reply_markup(
                reply_markup=media_filter_choice_keyboard(project_id)
            )

            return

        if action == "mediafilterset":

            project_id = int(parts[1])
            choice = parts[2]
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            settings_service.set_media_filter(project_id, choice)
            await force_refresh_routes()
            settings = settings_service.get_settings(project_id)

            await query.message.edit_reply_markup(
                reply_markup=project_filters_keyboard(project_id, settings)
            )

            return

        if action == "setwhitelist":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            _reset_waiting_states(user_id)
            CURRENT_PROJECT[user_id] = project_id
            WAITING_WHITELIST[user_id] = True

            await query.message.reply_text(
                "✅ Send Whitelist Keywords\n\n"
                "Comma-separated. Only messages containing at least one "
                "will be forwarded. Send `-` to clear."
            )

            return

        if action == "setblacklist":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            _reset_waiting_states(user_id)
            CURRENT_PROJECT[user_id] = project_id
            WAITING_BLACKLIST[user_id] = True

            await query.message.reply_text(
                "🚫 Send Blacklist Keywords\n\n"
                "Comma-separated. Messages containing any of these will "
                "be skipped. Send `-` to clear."
            )

            return

        if action == "setregex":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            _reset_waiting_states(user_id)
            CURRENT_PROJECT[user_id] = project_id
            WAITING_REGEX[user_id] = True

            await query.message.reply_text(
                "🔤 Send Regex Pattern\n\n"
                "Only messages whose text matches will be forwarded. "
                "Send `-` to clear."
            )

            return

        if action == "clearfilters":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            settings_service.update_settings(
                project_id,
                media_filter="all",
                keyword_whitelist="",
                keyword_blacklist="",
                regex_filter="",
            )
            await force_refresh_routes()

            settings = settings_service.get_settings(project_id)

            await query.message.edit_reply_markup(
                reply_markup=project_filters_keyboard(project_id, settings)
            )

            return

        # ======================================
        # STATS
        # ======================================

        if action == "stats":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            stats = stats_service.get_stats(project_id)

            await query.message.reply_text(
                f"📊 Stats - {project['name']}\n\n"
                f"✅ Forwarded: {stats['forwarded']}\n"
                f"❌ Failed: {stats['failed']}\n"
                f"🔁 Retried: {stats['retried']}\n"
                f"🧹 Filtered Out: {stats['filtered']}\n"
                f"🕐 Last Forward: {stats['last_forward_at'] or '-'}"
            )

            return

        # ======================================
        # LOGS
        # ======================================

        if action == "logs":

            project_id = int(parts[1])
            project = _get_owned_project(project_id, user_id)

            if project is None:
                await query.message.reply_text("❌ Project Not Found")
                return

            logs = log_service.get_logs(project_id, limit=15)

            if not logs:

                await query.message.reply_text("📜 No logs yet for this project.")
                return

            level_icon = {"forward": "✅", "error": "❌", "retry": "🔁"}

            lines = [
                f"{level_icon.get(row['level'], 'ℹ')} [{row['created_at']}] {row['message']}"
                for row in logs
            ]

            await query.message.reply_text(
                "📜 Recent Logs\n\n" + "\n".join(lines)
            )

            return

        # ======================================
        # ADMIN PANEL
        # ======================================

        if action == "admin":

            if user_id not in ADMIN_IDS:
                await query.message.reply_text("⛔ Admins only.")
                return

            sub_action = parts[1] if len(parts) > 1 else ""

            if sub_action == "refresh":

                await query.message.edit_text(
                    _admin_dashboard_text(context),
                    reply_markup=admin_keyboard
                )

                return

            if sub_action == "broadcast":

                _reset_waiting_states(user_id)
                WAITING_BROADCAST[user_id] = True

                await query.message.reply_text(
                    "📢 Send the message you want to broadcast to every bot user."
                )

                return

            if sub_action == "maintenance":

                context.bot_data["maintenance_mode"] = not context.bot_data.get(
                    "maintenance_mode", False
                )

                await query.message.edit_text(
                    _admin_dashboard_text(context),
                    reply_markup=admin_keyboard
                )

                return

            await query.message.reply_text("⚠ Unknown Admin Action")
            return

        # ======================================
        # UNKNOWN CALLBACK
        # ======================================

        await query.message.reply_text(
            "⚠ Unknown Action"
        )

    except (IndexError, ValueError):

        logger.warning("Malformed callback data received: %s", data)

        await query.message.reply_text(
            "⚠ This button is no longer valid. Please refresh with 📁 My Projects."
        )

    except Exception as e:

        logger.exception("Unhandled error in button_handler: %s", e)

        await query.message.reply_text(
            "⚠ Something went wrong while processing that action. Please try again."
        )
