from telegram import (
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

# ==========================================
# MAIN MENU
# ==========================================

main_menu = ReplyKeyboardMarkup(

    [

        ["➕ New Project"],

        ["📁 My Projects"],

        ["📊 Status", "⚙ Settings"]

    ],

    resize_keyboard=True,

    is_persistent=True

)


# ==========================================
# PROJECT KEYBOARD
# ==========================================

def project_keyboard(project_id, running=None):
    """
    ``running``: True/False if the caller already knows the project's
    current status - shows just the one relevant button (Stop while
    running, Start while stopped) so there's a single obvious tap.
    Left as None (both buttons shown) for callers that don't have the
    status handy, so nothing else has to change.
    """

    if running is True:
        start_stop_row = [
            InlineKeyboardButton("⏹ Stop", callback_data=f"stop:{project_id}")
        ]
    elif running is False:
        start_stop_row = [
            InlineKeyboardButton("▶ Start", callback_data=f"start:{project_id}")
        ]
    else:
        start_stop_row = [
            InlineKeyboardButton("▶ Start", callback_data=f"start:{project_id}"),
            InlineKeyboardButton("⏹ Stop", callback_data=f"stop:{project_id}"),
        ]

    return InlineKeyboardMarkup(

        [

            [

                InlineKeyboardButton(

                    "➕ Source",

                    callback_data=f"source:{project_id}"

                ),

                InlineKeyboardButton(

                    "➕ Destination",

                    callback_data=f"destination:{project_id}"

                )

            ],

            [

                InlineKeyboardButton(

                    "📥 Sources",

                    callback_data=f"listsource:{project_id}"

                ),

                InlineKeyboardButton(

                    "📤 Destinations",

                    callback_data=f"listdestination:{project_id}"

                )

            ],

            start_stop_row,

            [

                InlineKeyboardButton(
                    "🧪 Test All Destinations",
                    callback_data=f"testproject:{project_id}"
                )

            ],

            [

                InlineKeyboardButton(

                    "✏ Rename",

                    callback_data=f"rename:{project_id}"

                ),

                InlineKeyboardButton(

                    "🗑 Delete",

                    callback_data=f"delete:{project_id}"

                )

            ],

            [

                InlineKeyboardButton(
                    "⚙ Forward Settings",
                    callback_data=f"projsettings:{project_id}"
                ),

                InlineKeyboardButton(
                    "🧹 Filters",
                    callback_data=f"projfilters:{project_id}"
                )

            ],

            [

                InlineKeyboardButton(
                    "📊 Stats",
                    callback_data=f"stats:{project_id}"
                ),

                InlineKeyboardButton(
                    "📜 Logs",
                    callback_data=f"logs:{project_id}"
                )

            ]

        ]

    )


# ==========================================
# SOURCE ITEM KEYBOARD
# ==========================================

def source_item_keyboard(source_id, project_id, enabled=True):

    return InlineKeyboardMarkup(

        [

            [

                InlineKeyboardButton(
                    "⏸ Disable" if enabled else "▶ Enable",
                    callback_data=f"togglesource:{source_id}:{project_id}"
                ),

                InlineKeyboardButton(
                    "🗑 Delete Source",
                    callback_data=f"deletesource:{source_id}:{project_id}"
                )

            ],

            [

                InlineKeyboardButton(
                    "⬅ Back to Sources",
                    callback_data=f"listsource:{project_id}"
                )

            ]

        ]

    )


# ==========================================
# DESTINATION ITEM KEYBOARD
# ==========================================

def destination_item_keyboard(destination_id, project_id, enabled=True):

    return InlineKeyboardMarkup(

        [

            [

                InlineKeyboardButton(
                    "⏸ Disable" if enabled else "▶ Enable",
                    callback_data=f"toggledestination:{destination_id}:{project_id}"
                ),

                InlineKeyboardButton(
                    "🗑 Delete Destination",
                    callback_data=f"deletedestination:{destination_id}:{project_id}"
                )

            ],

            [

                InlineKeyboardButton(
                    "🧪 Test",
                    callback_data=f"testdestination:{destination_id}:{project_id}"
                )

            ],

            [

                InlineKeyboardButton(
                    "⬅ Back to Destinations",
                    callback_data=f"listdestination:{project_id}"
                )

            ]

        ]

    )


# ==========================================
# PROJECT FORWARD SETTINGS KEYBOARD
# ==========================================

def project_settings_keyboard(project_id, settings):

    mode = settings["mode"]
    silent = bool(settings["silent"])
    protect = bool(settings["protect_content"])
    albums = bool(settings["keep_media_groups"])

    return InlineKeyboardMarkup(

        [

            [
                InlineKeyboardButton(
                    f"Mode: {'📨 Forward' if mode == 'forward' else '📝 Copy'}",
                    callback_data=f"togglemode:{project_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    f"🔕 Silent: {'On' if silent else 'Off'}",
                    callback_data=f"togglesilent:{project_id}"
                ),
                InlineKeyboardButton(
                    f"🛡 Protect Content: {'On' if protect else 'Off'}",
                    callback_data=f"toggleprotect:{project_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    f"🖼 Keep Albums: {'On' if albums else 'Off'}",
                    callback_data=f"togglealbum:{project_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    f"⏱ Delay: {settings['delay_min']}-{settings['delay_max']}s",
                    callback_data=f"setdelay:{project_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    "⬅ Back to Project",
                    callback_data=f"backproject:{project_id}"
                )
            ]

        ]

    )


# ==========================================
# PROJECT FILTER SETTINGS KEYBOARD
# ==========================================

MEDIA_FILTER_CHOICES = (
    "all", "text", "photo", "video", "audio",
    "document", "voice", "sticker", "poll", "animation",
)


def project_filters_keyboard(project_id, settings):

    return InlineKeyboardMarkup(

        [

            [
                InlineKeyboardButton(
                    f"🎛 Media Type: {settings['media_filter']}",
                    callback_data=f"mediafilter:{project_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    "✅ Whitelist Keywords",
                    callback_data=f"setwhitelist:{project_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    "🚫 Blacklist Keywords",
                    callback_data=f"setblacklist:{project_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔤 Regex Filter",
                    callback_data=f"setregex:{project_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    "🧹 Clear All Filters",
                    callback_data=f"clearfilters:{project_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    "⬅ Back to Project",
                    callback_data=f"backproject:{project_id}"
                )
            ]

        ]

    )


def media_filter_choice_keyboard(project_id):

    rows = []
    row = []

    for choice in MEDIA_FILTER_CHOICES:

        row.append(
            InlineKeyboardButton(
                choice,
                callback_data=f"mediafilterset:{project_id}:{choice}"
            )
        )

        if len(row) == 3:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            "⬅ Back",
            callback_data=f"projfilters:{project_id}"
        )
    ])

    return InlineKeyboardMarkup(rows)


# ==========================================
# SETTINGS KEYBOARD
# ==========================================

settings_keyboard = InlineKeyboardMarkup(

    [

        [

            InlineKeyboardButton(
                "🔄 Refresh Status",
                callback_data="settings:refresh"
            )

        ]

    ]

)


# ==========================================
# ADMIN KEYBOARD
# ==========================================

admin_keyboard = InlineKeyboardMarkup(

    [

        [
            InlineKeyboardButton(
                "🔄 Refresh Dashboard",
                callback_data="admin:refresh"
            )
        ],

        [
            InlineKeyboardButton(
                "📢 Broadcast",
                callback_data="admin:broadcast"
            )
        ],

        [
            InlineKeyboardButton(
                "🛠 Toggle Maintenance Mode",
                callback_data="admin:maintenance"
            )
        ]

    ]

)