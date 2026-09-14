from __future__ import annotations

"""
Facilities Flow — Overdue Tasks (Building-First)
===================================================
When a user sends "Show overdue tasks":
  1. If user has access to multiple buildings → prompt building selection
  2. If user has access to only one building → show directly
  3. Fetch overdue tasks for selected building
  4. Display formatted overdue task list
"""

import logging

from whatsapp.ux import send_text, send_list_message
from facilities.auth import get_permitted_buildings, assert_building_access
from facilities.task_filter import (
    TaskFilterCriteria,
    filter_tasks,
    format_overdue_tasks,
    format_filtered_tasks,
)
from facilities.flows.router import set_session, clear_session

logger = logging.getLogger(__name__)


def handle_overdue_request(sender: str, user: dict, building: str | None = None):
    """
    Entry point for "show overdue tasks".

    If building is provided, show overdue for that building.
    If user has only one building, show it directly.
    Otherwise, prompt for building selection.
    """
    if building:
        show_overdue_tasks(sender, user, building)
        return

    buildings = get_permitted_buildings(user)
    # Filter to only non-Common buildings for overdue display
    buildings = [b for b in buildings if b != "Common"]

    if not buildings:
        send_text(sender, "You don't have access to any buildings.")
        return

    if len(buildings) == 1:
        # Single building → show directly
        show_overdue_tasks(sender, user, buildings[0])
        return

    # Multiple buildings → prompt selection
    prompt_overdue_building_selection(sender, user, buildings)


def prompt_overdue_building_selection(sender: str, user: dict,
                                       buildings: list[str] | None = None):
    """
    Show the building selection for overdue tasks.

    Step 1 of the overdue flow: "Please select the Building to view overdue tasks:"
    """
    if not buildings:
        buildings = get_permitted_buildings(user)
        buildings = [b for b in buildings if b != "Common"]

    set_session(sender, "overdue_tasks_building",
                context={"next_action": "overdue_tasks"})

    rows = [{"id": f"fac_overdue_bldg_{b}", "title": f"🏗️ {b}"} for b in buildings]

    if len(rows) > 10:
        rows = rows[:10]

    sections = [{"title": "Select Building", "rows": rows}]
    send_list_message(
        sender,
        "🔴 *Overdue Tasks — Select Building*\n\n"
        "Please select the Building to view overdue tasks:",
        "Select Building",
        sections,
    )


def show_overdue_tasks(sender: str, user: dict, building: str):
    """
    Show overdue tasks for a specific building.

    Step 2 of the overdue flow: fetches and displays overdue tasks.
    """
    clear_session(sender)

    # Enforce permission
    try:
        assert_building_access(user, building)
    except PermissionError as e:
        send_text(sender, f"🚫 {str(e)}")
        return

    # Fetch overdue tasks using the filter engine
    criteria = TaskFilterCriteria(building=building, overdue=True)
    overdue_tasks = filter_tasks(criteria, user)

    # Format and send
    msg = format_overdue_tasks(overdue_tasks, building)
    send_text(sender, msg)


def show_filtered_tasks(sender: str, user: dict, criteria: TaskFilterCriteria,
                          label: str | None = None):
    """
    Show filtered tasks for any combination of filters.

    Generic handler for all filter results.
    """
    clear_session(sender)

    tasks = filter_tasks(criteria, user)

    if not label:
        label = _build_filter_label(criteria)

    msg = format_filtered_tasks(tasks, label)

    # If too long, send as multiple messages
    if len(msg) > 4000:
        # Split into chunks
        lines = msg.split("\n")
        chunk = []
        chunk_len = 0
        for line in lines:
            if chunk_len + len(line) > 3500 and chunk:
                send_text(sender, "\n".join(chunk))
                chunk = []
                chunk_len = 0
            chunk.append(line)
            chunk_len += len(line)
        if chunk:
            send_text(sender, "\n".join(chunk))
    else:
        send_text(sender, msg)


def _build_filter_label(criteria: TaskFilterCriteria) -> str:
    """Build a human-readable label for filter results."""
    parts = []

    if criteria.employee_name:
        parts.append(f"{criteria.employee_name}'s")

    if criteria.overdue:
        parts.append("Overdue")
    elif criteria.future:
        parts.append("Future")
    elif criteria.status:
        parts.append(criteria.status)

    parts.append("Tasks")

    if criteria.building:
        parts.append(f"— {criteria.building}")

    if criteria.date_range_start and criteria.date_range_end:
        parts.append(f"({criteria.date_range_start} to {criteria.date_range_end})")

    return " ".join(parts)
