"""
Screen 10/13 — Building Filter
=================================
Building filter as List Message (4 options).
Typed names get fuzzy-matched.
Unrecognized names trigger "did you mean" List Message (Screen 13).
"""

import logging

from whatsapp.ux import send_text, send_list_message
from facilities.auth import get_permitted_buildings, fuzzy_match_building, get_fuzzy_building_suggestions
from facilities.flows.router import set_session, get_session, clear_session

logger = logging.getLogger(__name__)


def prompt_building_filter(sender: str, user: dict, next_action: str = "team_tasks"):
    """Show the building filter (Screen 10)."""
    buildings = get_permitted_buildings(user)
    set_session(sender, "building_filter", context={"next_action": next_action})

    rows = [{"id": f"fac_bldg_{b}", "title": b} for b in buildings]

    if len(rows) > 10:
        rows = rows[:10]

    sections = [{"title": "Select Building", "rows": rows}]
    send_list_message(
        sender,
        "🏗️ *Select a Building*\n\n"
        "Choose a building or type its name:",
        "Select Building",
        sections,
    )


def handle_building_text(sender: str, text: str, user: dict, session: dict):
    """Handle free-text building name input."""
    building = fuzzy_match_building(text)

    if building:
        from facilities.auth import assert_building_access
        try:
            assert_building_access(user, building)
        except PermissionError as e:
            send_text(sender, f"🚫 {str(e)}")
            return

        next_action = session.get("context_json", {}).get("next_action", "team_tasks")

        if next_action == "team_tasks":
            from facilities.flows.team_tasks import show_team_tasks
            show_team_tasks(sender, building, user)
        elif next_action == "create_task":
            from facilities.flows.create_task import handle_building_selection
            handle_building_selection(sender, building, user)
        elif next_action == "overdue_tasks":
            from facilities.flows.overdue_tasks import show_overdue_tasks
            show_overdue_tasks(sender, user, building)
        else:
            from facilities.flows.team_tasks import show_team_tasks
            show_team_tasks(sender, building, user)
    else:
        show_did_you_mean(sender, text, user)


def show_did_you_mean(sender: str, text: str, user: dict):
    """Show the "did you mean" prompt (Screen 13)."""
    suggestions = get_fuzzy_building_suggestions(text)
    permitted = get_permitted_buildings(user)

    # Filter to only permitted buildings
    suggestions = [s for s in suggestions if s["building"] in permitted]

    if not suggestions:
        send_text(
            sender,
            f"🤔 I couldn't find a building matching *\"{text}\"*.\n\n"
            f"Your available buildings: {', '.join(permitted)}\n\n"
            f"Please try again or select from the list."
        )
        prompt_building_filter(sender, user)
        return

    rows = [{"id": f"fac_bldg_{s['building']}", "title": s["building"]} for s in suggestions]
    sections = [{"title": "Did you mean...", "rows": rows}]

    send_list_message(
        sender,
        f"🤔 I couldn't find *\"{text}\"*. Did you mean one of these?",
        "Select Building",
        sections,
    )
