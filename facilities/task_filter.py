from __future__ import annotations

"""
Facilities Module — Task Filtering Engine
============================================
Reusable filtering engine that supports building, employee, status,
date range, overdue/future, and all combinations.

Usage:
    from facilities.task_filter import TaskFilterCriteria, filter_tasks

    criteria = TaskFilterCriteria(building="GEBB1", overdue=True)
    results = filter_tasks(criteria, user)

    # Or from natural language:
    criteria = parse_filter_from_text("show Vikramjeet overdue tasks in GEBB1", user)
    results = filter_tasks(criteria, user)
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional

from facilities.auth import get_permitted_buildings, assert_building_access
from facilities.sheets_client import list_rows_by_building
from facilities.owner_resolver import (
    resolve_position_to_user,
    resolve_user_to_positions,
    get_position_titles_for_user,
    match_employee_name,
    get_all_known_employee_names,
)
from facilities.config import BUILDING_TABS, VALID_STATUSES

logger = logging.getLogger(__name__)

# Statuses that exclude a task from "overdue" results
CLOSED_STATUSES = {"closed", "completed", "done"}

# Date formats commonly used in the Google Sheet
DATE_FORMATS = [
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %y",
    "%d-%b-%y",
]


@dataclass
class TaskFilterCriteria:
    """Criteria for filtering Facilities tasks."""
    building: Optional[str] = None
    employee_name: Optional[str] = None         # Resolved to owner positions
    owner_positions: Optional[list[str]] = None  # Direct position filter
    status: Optional[str] = None                 # "Open", "WIP", "Closed", etc.
    overdue: bool = False                        # Only overdue tasks
    future: bool = False                         # Only future tasks (target_date > today)
    date_range_start: Optional[str] = None       # YYYY-MM-DD
    date_range_end: Optional[str] = None         # YYYY-MM-DD
    date_field: str = "target_date"              # "target_date" or "created_date"


# ── Main Filter Function ─────────────────────────────────────────────────────

def filter_tasks(criteria: TaskFilterCriteria, user: dict) -> list[dict]:
    """
    Main filtering function. Applies all criteria and returns matching tasks.

    Steps:
        1. Resolve employee_name → owner_positions via owner_resolver
        2. Determine buildings from user permissions + criteria
        3. Fetch tasks from row_cache
        4. Apply all filters (status, overdue, date range, owner)
        5. Return filtered + enriched results

    Args:
        criteria: TaskFilterCriteria with the desired filters
        user: Authenticated user dict (with permitted_buildings)

    Returns:
        List of task dicts, each enriched with 'responsible_user' field
    """
    # 1. Resolve employee → owner positions
    effective_positions = criteria.owner_positions or []
    if criteria.employee_name:
        resolved = get_position_titles_for_user(
            criteria.employee_name,
            building=criteria.building
        )
        if resolved:
            effective_positions = resolved
        else:
            logger.warning(
                f"Employee '{criteria.employee_name}' has no mapped positions"
                + (f" for building {criteria.building}" if criteria.building else "")
            )
            return []  # No positions found → no tasks

    # 2. Determine which buildings to query
    permitted = get_permitted_buildings(user)
    if criteria.building:
        if criteria.building not in permitted:
            try:
                assert_building_access(user, criteria.building)
            except PermissionError:
                return []
        target_buildings = [criteria.building]
    elif effective_positions:
        # Determine buildings from position mappings
        pos_buildings = set()
        for pos_title in effective_positions:
            mapping = resolve_position_to_user(pos_title)
            if mapping and mapping.get("building"):
                pos_buildings.add(mapping["building"])
        # If positions have no building (cross-building), search all permitted
        if pos_buildings:
            target_buildings = [b for b in pos_buildings if b in permitted]
        else:
            target_buildings = permitted
    else:
        target_buildings = permitted

    if not target_buildings:
        return []

    # 3. Fetch tasks from row_cache
    # Live poll first for fresh data
    try:
        from facilities.sync_engine import poll_sheet_changes
        poll_sheet_changes()
    except Exception as e:
        logger.warning(f"Live poll in filter_tasks failed: {e}")

    all_tasks = []
    for building in target_buildings:
        tasks = list_rows_by_building(building)
        all_tasks.extend(tasks)

    if not all_tasks:
        return []

    # 4. Apply filters
    filtered = all_tasks

    # Filter by owner position
    if effective_positions:
        from facilities.owner_resolver import normalize_position_title
        pos_set = {p.lower() for p in effective_positions}
        norm_pos_set = {normalize_position_title(p) for p in effective_positions}
        emp_name_lower = (criteria.employee_name or "").strip().lower()

        filtered = [
            t for t in filtered
            if (t.get("owner") or "").strip().lower() in pos_set
            or normalize_position_title(t.get("owner") or "") in norm_pos_set
            or (emp_name_lower and (t.get("responsible_user") or "").strip().lower() == emp_name_lower)
            or (emp_name_lower and (t.get("owner") or "").strip().lower() == emp_name_lower)
        ]

    # Filter by status
    if criteria.status:
        status_lower = criteria.status.strip().lower()
        filtered = [
            t for t in filtered
            if (t.get("status") or "").strip().lower() == status_lower
        ]

    # Filter overdue
    if criteria.overdue:
        filtered = [t for t in filtered if is_task_overdue(t)]

    # Filter future
    if criteria.future:
        filtered = [t for t in filtered if is_task_future(t)]

    # Filter by date range
    if criteria.date_range_start or criteria.date_range_end:
        filtered = _filter_by_date_range(
            filtered,
            criteria.date_range_start,
            criteria.date_range_end,
            criteria.date_field,
        )

    # 5. Enrich each task with responsible_user
    for task in filtered:
        enrich_task_with_responsible(task)

    return filtered


# ── Overdue / Future Logic ───────────────────────────────────────────────────

def is_task_overdue(task: dict) -> bool:
    """
    Determine if a task is overdue.

    A task is overdue if:
        - target_date is in the past (before today)
        - status is NOT in closed/completed/done statuses
        - If delay_days from Sheet is available and > 0, task is overdue
    """
    status = (task.get("status") or "").strip().lower()
    if status in CLOSED_STATUSES:
        return False

    # Check Sheet's delay_days first (it has a formula)
    delay_str = (task.get("delay_days") or "").strip()
    if delay_str:
        try:
            delay_val = int(float(delay_str))
            if delay_val > 0:
                return True
        except (ValueError, TypeError):
            pass

    # Fall back to planned_date / target_date computation
    date_val = task.get("planned_date") or task.get("target_date")
    target_date = _parse_date(date_val)
    if not target_date:
        return False

    today = date.today()
    return target_date < today


def is_task_future(task: dict) -> bool:
    """
    Determine if a task is a future task (planned_date > today).
    """
    status = (task.get("status") or "").strip().lower()
    if status in CLOSED_STATUSES:
        return False

    date_val = task.get("planned_date") or task.get("target_date")
    target_date = _parse_date(date_val)
    if not target_date:
        return False

    return target_date > date.today()


def calculate_delay_days(task: dict) -> int:
    """
    Calculate delay days from planned_date / target_date vs today.

    If the Sheet provides delay_days (via formula), use that.
    Otherwise, compute from planned_date / target_date.

    Returns:
        Positive int for overdue days, 0 if not overdue or cannot determine
    """
    # Prefer Sheet formula value
    delay_str = (task.get("delay_days") or "").strip()
    if delay_str:
        try:
            return max(0, int(float(delay_str)))
        except (ValueError, TypeError):
            pass

    # Compute from planned_date / target_date
    date_val = task.get("planned_date") or task.get("target_date")
    target_date = _parse_date(date_val)
    if not target_date:
        return 0

    delta = (date.today() - target_date).days
    return max(0, delta)


# ── Task Enrichment ──────────────────────────────────────────────────────────

def enrich_task_with_responsible(task: dict) -> dict:
    """
    Add 'responsible_user' field by resolving the owner position title.

    Modifies task in-place and returns it.
    """
    owner = (task.get("owner") or "").strip()
    if not owner:
        task["responsible_user"] = None
        return task

    mapping = resolve_position_to_user(owner, building=task.get("building"))
    if mapping:
        task["responsible_user"] = mapping["user_name"]
    else:
        task["responsible_user"] = None

    return task


# ── Natural Language Parsing ─────────────────────────────────────────────────

def parse_filter_from_text(text: str, user: dict) -> TaskFilterCriteria:
    """
    Parse natural language text into TaskFilterCriteria.

    Handles patterns like:
        - "show overdue tasks"
        - "show Vikash tasks"
        - "show overdue tasks in GEBB2"
        - "show Vikramjeet's tasks between 20 and 29 Aug"
        - "show pending tasks for GEBB1"
        - "show Vikramjeet's overdue tasks in GEBB1"
        - "show tasks due this week"
        - "show tasks raised between 20 and 29 Aug"
        - "show future tasks for GETT"
        - "what tasks are overdue"
        - "which tasks are pending"
        - "show my tasks"

    Args:
        text: Raw user input
        user: Authenticated user dict

    Returns:
        TaskFilterCriteria with extracted filters
    """
    criteria = TaskFilterCriteria()
    clean = text.strip().lower()

    # 1. Extract building
    criteria.building = _extract_building(clean)

    # 2. Extract employee name
    criteria.employee_name = _extract_employee_name(clean)

    # 3. Check "my tasks" → resolve to current user's name
    if not criteria.employee_name and _is_my_tasks_query(clean):
        criteria.employee_name = user.get("name")

    # 4. Extract status
    criteria.status = _extract_status(clean)

    # 5. Extract overdue/future
    criteria.overdue = _is_overdue_query(clean)
    criteria.future = _is_future_query(clean)

    # 6. Extract date range
    date_info = _extract_date_range(clean)
    if date_info:
        criteria.date_range_start = date_info.get("start")
        criteria.date_range_end = date_info.get("end")
        criteria.date_field = date_info.get("field", "target_date")

    return criteria


# ── NL Parsing Helpers ───────────────────────────────────────────────────────

def _extract_building(text: str) -> Optional[str]:
    """Extract building name from text."""
    from facilities.auth import fuzzy_match_building

    # Check for explicit building mentions
    for pattern in [
        r'\b(?:in|for|of)\s+(gebb\s*[12]|gett|common)\b',
        r'\b(gebb\s*[12]|gett|common)\b',
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return fuzzy_match_building(m.group(1))

    return None


def _extract_employee_name(text: str) -> Optional[str]:
    """Extract employee name from text."""
    known_names = get_all_known_employee_names()

    # Remove common noise words for matching
    # Patterns: "show Vikash tasks", "show Vikramjeet's tasks", "tasks assigned to Vikash"
    for name in known_names:
        name_lower = name.lower()
        # Check for possessive: "Vikramjeet's"
        if f"{name_lower}'s" in text or f"{name_lower}s" in text:
            return name
        # Check for plain name mention
        if re.search(r'\b' + re.escape(name_lower) + r'\b', text):
            return name

    # Also check aliases
    alias_patterns = {
        "vikram": "Vikramjeet",
        "vikramjeet": "Vikramjeet",
        "anoop": "Anoop",
        "anup": "Anoop",
        "facility head": "Anoop",
        "facilities head": "Anoop",
        "head": "Anoop",
        "kanav": "Kanav",
        "kk": "Kanav",
        "director": "Kanav",
        "facility director": "Kanav",
        "facilities director": "Kanav",
        "vikash": "Vikash",
        "vikkas": "Vikash",
        "abhijeet": "Abhijeet",
    }
    for alias, canonical in alias_patterns.items():
        if re.search(r'\b' + re.escape(alias) + r"(?:'s)?\b", text):
            return canonical

    return None


def _extract_status(text: str) -> Optional[str]:
    """Extract status filter from text."""
    status_keywords = {
        "pending": "Open",
        "open": "Open",
        "wip": "WIP",
        "in progress": "WIP",
        "in-progress": "WIP",
        "closed": "Closed",
        "completed": "Closed",
        "done": "Closed",
        "on hold": "On Hold",
        "on-hold": "On Hold",
        "escalated": "Escalated",
        "blocked": "Escalated",
    }

    for keyword, status in status_keywords.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', text):
            return status

    return None


def _is_overdue_query(text: str) -> bool:
    """Check if the text is asking about overdue tasks."""
    overdue_patterns = [
        r'\boverdue\b',
        r'\bover\s*due\b',
        r'\bpast\s*due\b',
        r'\bdelayed\b',
        r'\blate\b',
        r'\bmissed\s*deadline\b',
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in overdue_patterns)


def _is_future_query(text: str) -> bool:
    """Check if the text is asking about future tasks."""
    future_patterns = [
        r'\bfuture\b',
        r'\bupcoming\b',
        r'\bnot\s*yet\s*due\b',
        r'\bdue\s*later\b',
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in future_patterns)


def _is_my_tasks_query(text: str) -> bool:
    """Check if the text is asking about the user's own tasks."""
    patterns = [
        r'\bmy\s*tasks?\b',
        r'\bassigned\s*to\s*me\b',
        r'\bmy\s*overdue\b',
        r'\bmy\s*pending\b',
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _extract_date_range(text: str) -> Optional[dict]:
    """
    Extract date range from text.

    Supports:
        - "between 20 and 29 Aug"
        - "from 20 Aug to 29 Aug"
        - "due this week"
        - "due between 20 and 29 Aug"
        - "raised between 20 and 29 Aug"

    Returns:
        dict with 'start', 'end' (YYYY-MM-DD), 'field' ("target_date" or "created_date")
        or None
    """
    result = {}

    # Determine which date field to use
    if re.search(r'\braised\b', text, re.IGNORECASE):
        result["field"] = "created_date"
    else:
        result["field"] = "target_date"

    # "this week"
    if re.search(r'\bthis\s+week\b', text, re.IGNORECASE):
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        result["start"] = start_of_week.isoformat()
        result["end"] = end_of_week.isoformat()
        return result

    # "next week"
    if re.search(r'\bnext\s+week\b', text, re.IGNORECASE):
        today = date.today()
        start_of_next_week = today + timedelta(days=(7 - today.weekday()))
        end_of_next_week = start_of_next_week + timedelta(days=6)
        result["start"] = start_of_next_week.isoformat()
        result["end"] = end_of_next_week.isoformat()
        return result

    # "today"
    if re.search(r'\btoday\b', text, re.IGNORECASE):
        today = date.today().isoformat()
        result["start"] = today
        result["end"] = today
        return result

    # "between X and Y Month" or "from X Month to Y Month"
    month_names = {
        "jan": 1, "january": 1, "feb": 2, "february": 2,
        "mar": 3, "march": 3, "apr": 4, "april": 4,
        "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "september": 9, "sept": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    # Pattern: "between 20 and 29 Aug" or "from 20 to 29 Aug"
    m = re.search(
        r'(?:between|from)\s+(\d{1,2})\s*(?:and|to|-)\s*(\d{1,2})\s+'
        r'(' + '|'.join(month_names.keys()) + r')\b',
        text, re.IGNORECASE
    )
    if m:
        day_start = int(m.group(1))
        day_end = int(m.group(2))
        month_str = m.group(3).lower()
        month = month_names.get(month_str)
        if month:
            year = date.today().year
            # If the month is in the past, assume next year
            if month < date.today().month:
                year += 1
            try:
                result["start"] = date(year, month, day_start).isoformat()
                result["end"] = date(year, month, day_end).isoformat()
                return result
            except ValueError:
                pass

    # Pattern: "from 20 Aug to 29 Aug"
    m = re.search(
        r'(?:from)\s+(\d{1,2})\s+(' + '|'.join(month_names.keys()) + r')\s+'
        r'(?:to|-)\s*(\d{1,2})\s+(' + '|'.join(month_names.keys()) + r')\b',
        text, re.IGNORECASE
    )
    if m:
        day_start = int(m.group(1))
        month_start = month_names.get(m.group(2).lower())
        day_end = int(m.group(3))
        month_end = month_names.get(m.group(4).lower())
        if month_start and month_end:
            year = date.today().year
            try:
                result["start"] = date(year, month_start, day_start).isoformat()
                result["end"] = date(year, month_end, day_end).isoformat()
                return result
            except ValueError:
                pass

    return None if "start" not in result else result


# ── Formatting Helpers ───────────────────────────────────────────────────────

def format_overdue_tasks(tasks: list[dict], building: str) -> str:
    """
    Format overdue tasks for WhatsApp display.

    Returns a formatted string matching the spec:
        🔴 Overdue Tasks — GEBB1
        1. Task: ...
           Project: ...
           Owner: ...
           Responsible: ...
           Target Date: ...
           Delay: X days
    """
    if not tasks:
        return f"✅ *No overdue tasks found for {building}.*"

    lines = [f"🔴 *Overdue Tasks — {building}*\n"]

    for i, task in enumerate(tasks, 1):
        ref = task.get("ref_no", "—")
        issue = task.get("issue_action", "No description")
        owner = task.get("owner", "Unassigned")
        responsible = task.get("responsible_user") or "Unknown"
        planned = task.get("planned_date") or task.get("target_date", "—") or "—"
        est_comp = task.get("estimated_completion_date") or "—"
        delay = calculate_delay_days(task)
        task_type = task.get("type", "General")

        lines.append(f"*{i}. Task:* {issue}")
        lines.append(f"   *Ref:* {ref}")
        lines.append(f"   *Type:* {task_type}")
        lines.append(f"   *Owner:* {owner}")
        lines.append(f"   *Responsible:* {responsible}")
        lines.append(f"   *Planned Date:* {planned}")
        lines.append(f"   *Estimated Completion Date:* {est_comp}")
        lines.append(f"   *Delay:* {delay} day{'s' if delay != 1 else ''}")
        lines.append("")

    lines.append(f"_Total overdue: {len(tasks)}_")
    return "\n".join(lines)


def format_filtered_tasks(tasks: list[dict], label: str) -> str:
    """
    Format filtered tasks for WhatsApp display.

    Generic formatter for any filter result.
    """
    if not tasks:
        return f"📋 *{label}*\n\nNo matching tasks found."

    from facilities.config import RAG_STATUS_MAP

    lines = [f"📋 *{label}*\n"]

    for i, task in enumerate(tasks[:15], 1):  # Limit to 15 for readability
        ref = task.get("ref_no", "—")
        issue = task.get("issue_action", "No description")
        if len(issue) > 50:
            issue = issue[:47] + "..."
        status = task.get("status", "Open")
        rag = RAG_STATUS_MAP.get(status, {"emoji": "⚪", "label": status})
        building = task.get("building", "")
        owner = task.get("owner", "Unassigned")
        responsible = task.get("responsible_user")
        planned = task.get("planned_date") or task.get("target_date", "—") or "—"
        est_comp = task.get("estimated_completion_date")
        date_display = f"📅 {planned}"
        if est_comp:
            date_display += f" (Est: {est_comp})"

        lines.append(f"{rag['emoji']} *{ref}* [{building}] — {issue}")
        owner_display = f"{owner}"
        if responsible and responsible.lower() != owner.lower():
            owner_display += f" ({responsible})"
        lines.append(f"   👤 {owner_display} | {date_display}")
        lines.append("")

    if len(tasks) > 15:
        lines.append(f"_Showing 15 of {len(tasks)} tasks._")

    lines.append(f"\n_Total: {len(tasks)}_")
    return "\n".join(lines)


# ── Date Parsing Helpers ─────────────────────────────────────────────────────

def _parse_date(date_str: str | None) -> date | None:
    """Parse a date string from the Google Sheet into a date object."""
    if not date_str:
        return None

    clean = date_str.strip()
    if not clean:
        return None

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue

    # Try dateutil as fallback
    try:
        from dateutil import parser as date_parser
        return date_parser.parse(clean, dayfirst=True).date()
    except Exception:
        pass

    return None


def _filter_by_date_range(tasks: list[dict], start_str: str | None,
                           end_str: str | None, date_field: str) -> list[dict]:
    """Filter tasks by date range on a specific field."""
    start_date = _parse_date(start_str) if start_str else None
    end_date = _parse_date(end_str) if end_str else None

    if not start_date and not end_date:
        return tasks

    result = []
    for task in tasks:
        val = task.get(date_field)
        if not val and date_field in ("planned_date", "target_date"):
            val = task.get("planned_date") or task.get("target_date")
        task_date = _parse_date(val)
        if not task_date:
            continue

        if start_date and task_date < start_date:
            continue
        if end_date and task_date > end_date:
            continue

        result.append(task)

    return result
