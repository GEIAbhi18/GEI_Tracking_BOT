from __future__ import annotations
import re
import logging
from datetime import datetime, timedelta, timezone
from whatsapp.ux import send_list_message, send_interactive_buttons, send_text
from elara.config import ELARA_DEPARTMENTS, VALID_PRIORITIES
from elara.db import get_projects, create_task, get_project_by_id
from elara.auth import get_elara_team_members, is_elara_admin
from elara.session import set_elara_session, clear_elara_session, get_elara_session
from elara.flows.task_card import send_elara_task_card
from core.utils import parse_human_date

logger = logging.getLogger(__name__)


def parse_task_intent_from_text(text: str, user: dict) -> dict:
    """
    Extract title, project/dept, priority, due date, and assignee from natural language.
    """
    entities = {
        "title": None,
        "project_id": None,
        "department": None,
        "priority": "medium",
        "due_date": None,
        "assignee": None,
    }

    clean = text.strip()

    # Priority extraction
    if re.search(r'\b(urgent|critical|high priority|priority high)\b', clean, re.I):
        entities["priority"] = "high"
    elif re.search(r'\b(low priority|priority low)\b', clean, re.I):
        entities["priority"] = "low"
    elif re.search(r'\b(medium priority|priority medium)\b', clean, re.I):
        entities["priority"] = "medium"

    # Department detection from 6 departments
    for dept in ELARA_DEPARTMENTS:
        if dept.lower() in clean.lower():
            # pyrefly: ignore [bad-assignment]
            entities["department"] = dept
            break

    # Date extraction (e.g., "due tomorrow", "by Friday", "due 2026-09-20")
    date_match = re.search(r'\b(?:due|by|deadline|on)\s+([a-zA-Z0-9\s\-]+?)(?:\s+(?:priority|for|under|assigned|$))', clean, re.I)
    if date_match:
        raw_date_str = date_match.group(1).strip()
        parsed = parse_human_date(raw_date_str)
        if parsed:
            entities["due_date"] = parsed

    # Assignee extraction from elara_users
    team_members = get_elara_team_members()
    for m in team_members:
        name = m.get("name", "")
        if name and re.search(rf'\b(?:for|to|assign(?:ed)? to)\s+{re.escape(name)}\b', clean, re.I):
            entities["assignee"] = name
            break
        elif name and name.lower() in clean.lower() and len(name) > 2:
            entities["assignee"] = name

    # Clean title
    title = clean
    # Strip trigger words
    title = re.sub(r'^(?:please\s+)?(?:create|add|new)\s+(?:a\s+)?(?:task|elara task)\s*(?:to|for|called|named|:)?\s*', '', title, flags=re.I)
    # Strip trailing due/priority/assignee clauses
    title = re.sub(r'\s+(?:priority\s+\w+|due\s+.*|by\s+.*|assigned\s+to\s+.*)$', '', title, flags=re.I).strip()

    if title:
        entities["title"] = title

    return entities


def start_create_task_flow(to: str, user: dict, prefill: dict | None = None):
    """
    Start task creation. If title and project are already known, create directly.
    Otherwise guide the user through missing fields.
    """
    draft = prefill.copy() if prefill else {}

    # If title already extracted from natural language
    title = draft.get("title")

    # If project not known, see if department is known or user belongs to a specific department
    project_id = draft.get("project_id")
    if not project_id and draft.get("department"):
        dept_projects = get_projects(draft["department"])
        if dept_projects:
            project_id = dept_projects[0]["id"]
            draft["project_id"] = project_id

    # If user belongs to a specific department and is not admin, default to their department
    if not project_id and not is_elara_admin(user) and user.get("department"):
        user_dept = user.get("department")
        dept_projects = get_projects(user_dept)
        if dept_projects:
            project_id = dept_projects[0]["id"]
            draft["project_id"] = project_id
            draft["department"] = user_dept

    # If both title and project are known, proceed to finalize or ask confirmation
    if title and project_id:
        return finalize_task_creation(to, user, draft)

    # If project is missing, ask for project selection
    if not project_id:
        projects = get_projects()
        if not projects:
            return send_text(to, "⚠️ No projects found in Elara Home. Please create a project first.")

        rows = []
        for p in projects[:10]:
            rows.append({
                "id": f"elara_tproj_{p['id']}",
                "title": p["name"][:24],
                "description": f"Dept: {p.get('department', 'General')}"[:72],
            })

        sections = [{"title": "Select Project", "rows": rows}]
        set_elara_session(to, "create_task_select_project", draft=draft)
        return send_list_message(
            to,
            "➕ *Create Elara Task*\n\nWhich project does this task belong to?",
            "Select Project",
            sections,
        )

    # Project is known, prompt for title
    set_elara_session(to, "create_task_title", draft=draft)
    proj = get_project_by_id(project_id)
    proj_name = proj.get("name", "Project") if proj else "Project"
    return send_text(
        to,
        f"➕ Creating task under *{proj_name}*.\n\n"
        f"Please enter the *Task Title*:"
    )


def handle_task_project_selection(to: str, project_id: str, user: dict, session: dict):
    """Handle project selection for task creation."""
    draft = session.get("draft", {})
    draft["project_id"] = project_id
    proj = get_project_by_id(project_id)
    if proj:
        draft["department"] = proj.get("department")

    if draft.get("title"):
        return finalize_task_creation(to, user, draft)

    set_elara_session(to, "create_task_title", draft=draft)
    proj_name = proj.get("name", "Project") if proj else "Project"
    return send_text(
        to,
        f"✅ Selected Project: *{proj_name}*\n\n"
        f"Please enter the *Task Title*:"
    )


def handle_task_title_input(to: str, text: str, user: dict, session: dict):
    """Receive task title."""
    clean_title = text.strip()
    if not clean_title:
        return send_text(to, "Please enter a valid Task Title:")

    draft = session.get("draft", {})
    draft["title"] = clean_title

    # Ask for priority
    set_elara_session(to, "create_task_priority", draft=draft)
    buttons = [
        {"id": "elara_tpri_medium", "title": "Medium Priority"},
        {"id": "elara_tpri_high", "title": "High Priority"},
        {"id": "elara_tpri_low", "title": "Low Priority"},
    ]
    return send_interactive_buttons(
        to,
        f"Task: *{clean_title}*\n\nSelect task priority:",
        buttons,
    )


def handle_task_priority_selection(to: str, priority: str, user: dict, session: dict):
    """Receive task priority and ask for due date."""
    draft = session.get("draft", {})
    draft["priority"] = priority.lower() if priority in VALID_PRIORITIES else "medium"

    set_elara_session(to, "create_task_due_date", draft=draft)
    buttons = [
        {"id": "elara_tdue_tomorrow", "title": "Tomorrow"},
        {"id": "elara_tdue_3days", "title": "In 3 Days"},
        {"id": "elara_tdue_skip", "title": "Skip Due Date"},
    ]
    return send_interactive_buttons(
        to,
        f"Priority set to *{draft['priority'].capitalize()}*.\n\n"
        f"When is this task due? You can type a date (e.g. *tomorrow*, *next Monday*, *Sep 25*) or tap an option below:",
        buttons,
    )


def handle_task_due_date_input(to: str, text: str, user: dict, session: dict):
    """Receive task due date input."""
    draft = session.get("draft", {})
    clean_text = text.strip().lower()

    if clean_text in ("skip", "skip due date", "none", "no"):
        draft["due_date"] = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    elif clean_text == "tomorrow":
        draft["due_date"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    elif clean_text == "in 3 days":
        draft["due_date"] = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    else:
        parsed = parse_human_date(clean_text)
        if parsed:
            draft["due_date"] = parsed
        else:
            draft["due_date"] = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()

    return finalize_task_creation(to, user, draft)


def finalize_task_creation(to: str, user: dict, draft: dict):
    """Create the task in elara_tasks table and show card."""
    title = draft.get("title", "New Task")
    project_id = draft.get("project_id")

    # Fallback to first project if none specified
    if not project_id:
        projects = get_projects()
        if projects:
            project_id = projects[0]["id"]
        else:
            clear_elara_session(to)
            return send_text(to, "❌ No Elara projects available to assign task to.")

    priority = draft.get("priority", "medium")
    due_date = draft.get("due_date") or (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    description = draft.get("description")

    # Assignee logic:
    # If assignee specified in draft, use it
    # Else if user is team member, assign to themselves
    # Else default to user's name
    assignee = draft.get("assignee")
    if not assignee:
        assignee = user.get("name") or "Developer"

    assignees = [assignee]

    creator_name = user.get("name") or "Team Member"
    creator_role = user.get("role") or "Team Member"

    # Insert into elara_tasks
    created_task = create_task(
        title=title,
        project_id=project_id,
        description=description,
        priority=priority,
        due_date=due_date,
        assigned_users=assignees,
        status="pending",
        created_by=creator_name,
    )

    # Record provenance comment in elara_comments and elara_tasks
    try:
        from elara.db import add_comment
        add_comment(
            task_id=created_task["id"],
            user_name=creator_name,
            user_role=creator_role,
            content=f"Task created by {creator_name}",
        )
    except Exception as cmt_err:
        logger.warning(f"Could not add creation comment for Elara task {created_task.get('id')}: {cmt_err}")

    clear_elara_session(to)
    send_text(to, "✅ *Elara Task Created Successfully!*")
    return send_elara_task_card(to, created_task)
