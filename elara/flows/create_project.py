from __future__ import annotations
import logging
from whatsapp.ux import send_list_message, send_interactive_buttons, send_text
from elara.config import ELARA_DEPARTMENTS, DEPARTMENT_DESCRIPTIONS
from elara.db import create_project, get_projects
from elara.session import set_elara_session, clear_elara_session, get_elara_session

logger = logging.getLogger(__name__)


def start_create_project_flow(to: str, user: dict, initial_department: str | None = None):
    """Initiate the project creation flow."""
    if initial_department and initial_department in ELARA_DEPARTMENTS:
        # Department is already known, prompt for project name
        set_elara_session(to, "create_proj_name", draft={"department": initial_department})
        return send_text(
            to,
            f"📁 Creating project under *{initial_department}*.\n\n"
            f"Please enter the *Project Name*:"
        )

    # Show 6 departments list to pick from
    rows = []
    for idx, dept in enumerate(ELARA_DEPARTMENTS):
        desc = DEPARTMENT_DESCRIPTIONS.get(dept, "")
        rows.append({
            "id": f"elara_pdept_{idx}",
            "title": dept[:24],
            "description": desc[:72],
        })

    sections = [{"title": "Elara Home Departments", "rows": rows}]
    set_elara_session(to, "create_proj_select_dept")
    return send_list_message(
        to,
        "📁 *Create New Project*\n\nWhich department does this project belong to?",
        "Select Department",
        sections,
    )


def handle_project_department_selection(to: str, dept_idx_or_name: str, user: dict):
    """Handle department selection for project creation."""
    dept_name = None
    if dept_idx_or_name.isdigit():
        idx = int(dept_idx_or_name)
        if 0 <= idx < len(ELARA_DEPARTMENTS):
            dept_name = ELARA_DEPARTMENTS[idx]
    else:
        for d in ELARA_DEPARTMENTS:
            if d.lower() == dept_idx_or_name.strip().lower():
                dept_name = d
                break

    if not dept_name:
        dept_name = ELARA_DEPARTMENTS[0]

    set_elara_session(to, "create_proj_name", draft={"department": dept_name})
    return send_text(
        to,
        f"✅ Selected Department: *{dept_name}*\n\n"
        f"Please enter the *Project Name*:\n"
        f"_(e.g., 'Villa Phase 2 Site Prep', 'Quarterly Audit')_"
    )


def handle_project_name_input(to: str, text: str, user: dict, session: dict):
    """Receive project name and ask for optional description."""
    clean_name = text.strip()
    if not clean_name:
        return send_text(to, "Please enter a valid Project Name:")

    draft = session.get("draft", {})
    draft["name"] = clean_name
    set_elara_session(to, "create_proj_desc", draft=draft)

    # Quick skip button
    buttons = [
        {"id": "elara_proj_skip_desc", "title": "Skip Description"},
        {"id": "elara_cancel", "title": "Cancel"},
    ]
    return send_interactive_buttons(
        to,
        f"Project Name: *{clean_name}*\n\n"
        f"Enter a brief description for this project, or tap *Skip Description*:",
        buttons,
    )


def handle_project_description_input(to: str, text: str, user: dict, session: dict):
    """Save project with description."""
    draft = session.get("draft", {})
    dept = draft.get("department", "Project Administration")
    name = draft.get("name", "New Project")
    desc = text.strip() if text.strip().lower() not in ("skip", "none", "skip description") else None

    # Insert into elara_projects table
    created = create_project(name=name, department=dept, description=desc)
    clear_elara_session(to)

    buttons = [
        {"id": f"elara_addtask_proj_{created['id']}", "title": "Add Task to Project"},
        {"id": "elara_home", "title": "Elara Home Menu"},
    ]

    msg = (
        f"🎉 *Project Created Successfully!*\n\n"
        f"📁 *Name:* {created['name']}\n"
        f"🏢 *Department:* {created['department']}\n"
        f"📝 *Description:* {created.get('description', 'None')}\n"
        f"🆔 `ID: {created['id']}`\n\n"
        f"This project is now live on the Kanban board! 🚀"
    )
    return send_interactive_buttons(to, msg, buttons)
