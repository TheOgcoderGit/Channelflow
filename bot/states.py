# ==========================================
# USER STATES
# ==========================================
# Every WAITING_* dict is keyed by telegram user id and cleared by
# handlers._reset_waiting_states() whenever the user navigates away,
# so a stale flag can never swallow an unrelated future message.

# Waiting for project name
WAITING_PROJECT_NAME = {}

# Waiting for source username
WAITING_SOURCE = {}

# Waiting for destination username
WAITING_DESTINATION = {}

# Waiting for rename project
WAITING_RENAME = {}

# Waiting for "min,max" delay input
WAITING_DELAY = {}

# Waiting for whitelist keyword input
WAITING_WHITELIST = {}

# Waiting for blacklist keyword input
WAITING_BLACKLIST = {}

# Waiting for regex filter input
WAITING_REGEX = {}

# Waiting for admin broadcast message
WAITING_BROADCAST = {}

# Current selected project
CURRENT_PROJECT = {}

# Current selected source
CURRENT_SOURCE = {}

# Current selected destination
CURRENT_DESTINATION = {}

# Temporary user data
USER_CACHE = {}
