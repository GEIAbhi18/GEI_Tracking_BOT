"""
GEI Bot — Friendly Error Message Handler
==========================================
Returns short, friendly, actionable error messages in plain English.
No technical jargon, no stack traces, no generic "Something went wrong."

RULES:
1. Always acknowledge what the user tried to do (if inferable)
2. One line for what went wrong — simply
3. One concrete example of how to say it correctly
4. Never use: error, exception, failed, invalid, null, undefined, parsing
5. Keep entire message under 3 lines
6. Match user's language — Hindi/Hinglish → respond in Hinglish

FAILURE TYPES:
    intent_unclear, task_not_found, project_not_found, missing_info,
    photo_required, permission_denied, duplicate_update, system_unavailable
"""

import logging
import re

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Hinglish / Hindi Detection
# ──────────────────────────────────────────────────────────────────────────────

# Common Hindi/Hinglish words that appear in messages from site workers
_HINGLISH_MARKERS = [
    "kya", "hai", "ho", "kaam", "bhai", "yaar", "karo", "kar", "bata",
    "dikhao", "dekho", "batao", "mujhe", "mera", "kaise", "kyun", "nahi",
    "haan", "aur", "wala", "kab", "kahan", "kaun", "kitna", "theek",
    "accha", "sahi", "galat", "kal", "aaj", "abhi", "jaldi", "ruk",
    "chal", "bhej", "bhejo", "photo", "bhejdo", "bolo", "bola", "hogya",
    "hogaya", "hua", "kiya", "kardiya", "kardia", "kardena", "krdena",
    "krdo", "krna", "krke", "krdia", "nhi", "ni", "mt", "toh",
    "bohot", "bahut", "thoda", "zyada", "jyada", "idhar", "udhar",
]

def _is_hinglish(text: str) -> bool:
    """Detect if the user's message is in Hinglish/Hindi."""
    if not text:
        return False
    words = re.findall(r'[a-zA-Z]+', text.lower())
    hinglish_count = sum(1 for w in words if w in _HINGLISH_MARKERS)
    return hinglish_count >= 2 or (len(words) <= 3 and hinglish_count >= 1)


# ──────────────────────────────────────────────────────────────────────────────
# Core Error Messages (English + Hinglish variants)
# ──────────────────────────────────────────────────────────────────────────────

_ERROR_TEMPLATES = {
    "intent_unclear": {
        "en": (
            "Couldn't quite get that — were you updating a task or checking something?\n"
            "Try: 'Waterproofing 60% done' or 'show my tasks'\n"
            "Or type 'help' to see what I can do"
        ),
        "hi": (
            "Samajh nahi aaya — kya aap task update kar rahe the?\n"
            "Try karo: 'Waterproofing 60% done' ya 'show my tasks'\n"
            "Ya 'help' likho to sab commands dikh jayenge"
        ),
    },
    "task_not_found": {
        "en": (
            "Couldn't find that task — try using the exact task name.\n"
            "Try: 'show my tasks' to see your list"
        ),
        "hi": (
            "Yeh task nahi mila — sahi naam use karo.\n"
            "Try karo: 'show my tasks' se apni list dekho"
        ),
    },
    "project_not_found": {
        "en": (
            "That project name didn't match anything.\n"
            "Try: 'show projects' to see all active projects"
        ),
        "hi": (
            "Yeh project nahi mila.\n"
            "Try karo: 'show projects' se sab projects dekho"
        ),
    },
    "missing_info": {
        "en": (
            "Almost got it — just need a bit more detail.\n"
            "Try: '[task name] [progress]% done' e.g. 'slope 40% done'"
        ),
        "hi": (
            "Almost ho gaya — thoda aur detail chahiye.\n"
            "Try karo: '[task name] [progress]% done' jaise 'slope 40% done'"
        ),
    },
    "photo_required": {
        "en": (
            "To mark this task complete, please attach a photo as proof.\n"
            "Send the photo with a caption like: 'Top Terrace waterproofing done'"
        ),
        "hi": (
            "Task complete karne ke liye ek photo bhejo as proof.\n"
            "Photo ke saath likho: 'Top Terrace waterproofing done'"
        ),
    },
    "permission_denied": {
        "en": (
            "That action is only available to directors.\n"
            "If this is a mistake, contact Kanav."
        ),
        "hi": (
            "Yeh action sirf directors ke liye hai.\n"
            "Agar galti hai toh Kanav ko contact karo."
        ),
    },
    "duplicate_update": {
        "en": (
            "Looks like this task was already updated recently.\n"
            "If something changed, say: 'update slope to 65%'"
        ),
        "hi": (
            "Yeh task abhi update hua tha.\n"
            "Agar kuch badla hai toh bolo: 'update slope to 65%'"
        ),
    },
    "system_unavailable": {
        "en": (
            "The system is a little slow right now — please try again in a moment.\n"
            "Your message was not lost."
        ),
        "hi": (
            "System thoda slow hai abhi — ek minute mein phir try karo.\n"
            "Aapka message save hai, kuch nahi gaya."
        ),
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def get_error_message(failure_type: str, user_message: str = "", context_hint: str = "") -> str:
    """
    Return a friendly, actionable error message for the given failure type.

    Args:
        failure_type:  One of the keys in _ERROR_TEMPLATES
        user_message:  The original message the user sent (used for language detection)
        context_hint:  Optional extra context to personalize the message
                       (e.g. a task name or project name that was attempted)

    Returns:
        A short, friendly string to send back to the user — never empty.
    """
    lang = "hi" if _is_hinglish(user_message) else "en"

    template = _ERROR_TEMPLATES.get(failure_type)
    if not template:
        logger.warning(f"Unknown failure_type '{failure_type}' — falling back to intent_unclear")
        template = _ERROR_TEMPLATES["intent_unclear"]

    msg = template.get(lang, template["en"])

    # Inject context hint when available (e.g. task/project name)
    if context_hint:
        # Append the context as a subtle inline reference
        if failure_type == "task_not_found":
            if lang == "hi":
                msg = f"'{context_hint}' naam ka task nahi mila — sahi naam use karo.\nTry karo: 'show my tasks' se apni list dekho"
            else:
                msg = f"Couldn't find a task called '{context_hint}' — try using the exact name.\nTry: 'show my tasks' to see your list"
        elif failure_type == "project_not_found":
            if lang == "hi":
                msg = f"'{context_hint}' naam ka project nahi mila.\nTry karo: 'show projects' se sab projects dekho"
            else:
                msg = f"'{context_hint}' didn't match any project.\nTry: 'show projects' to see all active projects"

    # SAFETY: Never return empty
    if not msg or not msg.strip():
        msg = _ERROR_TEMPLATES["intent_unclear"]["en"]

    return msg


def friendly_task_not_found(task_query: str, user_message: str = "") -> str:
    """Shortcut for task_not_found with the queried name as context."""
    return get_error_message("task_not_found", user_message=user_message, context_hint=task_query)


def friendly_project_not_found(project_query: str, user_message: str = "") -> str:
    """Shortcut for project_not_found with the queried name as context."""
    return get_error_message("project_not_found", user_message=user_message, context_hint=project_query)


def friendly_clarify(user_message: str = "") -> str:
    """Shortcut for intent_unclear."""
    return get_error_message("intent_unclear", user_message=user_message)


def friendly_system_error(user_message: str = "") -> str:
    """Shortcut for system_unavailable — used when exceptions bubble up."""
    return get_error_message("system_unavailable", user_message=user_message)


def friendly_missing_info(user_message: str = "") -> str:
    """Shortcut for missing_info."""
    return get_error_message("missing_info", user_message=user_message)


def friendly_permission_denied(user_message: str = "") -> str:
    """Shortcut for permission_denied."""
    return get_error_message("permission_denied", user_message=user_message)
