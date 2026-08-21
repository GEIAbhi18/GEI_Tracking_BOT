"""
Screen 01 — Home / Greeting
=============================
Shows role, permitted buildings, and a List Message with 5 actions.
5 actions → List Message (not Reply Buttons per WhatsApp rules).
"""

import logging
from whatsapp.ux import send_text, send_list_message
from facilities.auth import get_permitted_buildings

logger = logging.getLogger(__name__)


def show_home(sender: str, user: dict):
    """Send the Facilities home menu (Screen 01)."""
    from facilities.flows.router import clear_session
    clear_session(sender)

    name = user.get("name", "there")
    role = user.get("role", "Team Member")
    buildings = get_permitted_buildings(user)
    buildings_str = ", ".join(buildings) if buildings else "None assigned"

    greeting = (
        f"👋 Hello *{name}*!\n\n"
        f"🏢 *Role:* {role}\n"
        f"🏗️ *Buildings:* {buildings_str}\n\n"
        f"How can I help you today?"
    )

    rows = [
        {"id": "fac_my_tasks", "title": "📋 My Tasks", "description": "View your assigned tasks"},
        {"id": "fac_team_tasks", "title": "👥 Team Tasks", "description": "View tasks by building"},
        {"id": "fac_completed_tasks", "title": "🟢 Completed Tasks", "description": "View closed/completed tasks"},
        {"id": "fac_create_task", "title": "➕ Create Task", "description": "Create a new facilities task"},
        {"id": "fac_summary", "title": "📊 Summary", "description": "Task counts & status overview"},
        {"id": "fac_sync_status", "title": "🔗 Sync Status", "description": "Google Sheets sync health"},
    ]

    sections = [{"title": "Facilities Menu", "rows": rows}]
    send_list_message(sender, greeting, "Open Menu", sections)
