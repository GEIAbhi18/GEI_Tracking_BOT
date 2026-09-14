from __future__ import annotations
import logging
from whatsapp.ux import send_list_message, send_interactive_buttons, send_text
from elara.config import ELARA_DEPARTMENTS, STATUS_DISPLAY_NAMES
from elara.db import get_tasks, get_projects, get_project_by_id
from elara.auth import is_elara_admin

logger = logging.getLogger(__name__)


def show_team_tasks(to: str, user: dict, department: str | None = None):
    """Display active Elara Home team tasks, optionally filtered by department."""
    dept = department
    if not dept and not is_elara_admin(user) and user.get("department"):
        dept = user.get("department")

    tasks = get_tasks(department=dept)

    dept_label = f" ({dept})" if dept else ""
    if not tasks:
        buttons = [
            {"id": "elara_create_task", "title": "Create First Task"},
            {"id": "elara_home", "title": "Elara Home Menu"},
        ]
        return send_interactive_buttons(
            to,
            f"📋 *Elara Home Team Tasks*{dept_label}\n\nNo tasks found. Would you like to create one?",
            buttons,
        )

    rows = []
    for t in tasks[:10]:
        status_raw = str(t.get("status") or "pending")
        st_name = STATUS_DISPLAY_NAMES.get(status_raw) or status_raw.capitalize() or "Pending"
        assignees = t.get("assigned_users") or []
        assignee_str = f"👤 {assignees[0]}" if assignees else ""
        t_title = str(t.get("title") or "Task")
        rows.append({
            "id": f"elara_view_{t['id']}",
            "title": f"[{st_name[:4]}] {t_title}"[:24],
            "description": f"{assignee_str} • {str(t.get('priority') or 'medium').capitalize()}"[:72],
        })

    sections = [{"title": f"Active Tasks ({len(tasks)})", "rows": rows}]
    return send_list_message(
        to,
        f"📋 *Elara Home Team Tasks*{dept_label}\nShowing {min(10, len(tasks))} of {len(tasks)} tasks:",
        "View Task Details",
        sections,
    )


def show_my_tasks(to: str, user: dict):
    """Display tasks assigned to the current user."""
    user_name = user.get("name", "")
    tasks = get_tasks(assigned_user=user_name)

    if not tasks:
        buttons = [
            {"id": "elara_team_tasks", "title": "View All Tasks"},
            {"id": "elara_create_task", "title": "Create a Task"},
        ]
        return send_interactive_buttons(
            to,
            f"👤 *My Tasks — {user_name}*\n\nYou currently have no tasks assigned to you.",
            buttons,
        )

    rows = []
    for t in tasks[:10]:
        status_raw = str(t.get("status") or "pending")
        st_name = STATUS_DISPLAY_NAMES.get(status_raw) or status_raw.capitalize() or "Pending"
        due = t.get("due_date", "")
        if "T" in str(due):
            due = str(due).split("T")[0]
        due_str = f"Due: {due}" if due else ""
        t_title = str(t.get("title") or "Task")
        rows.append({
            "id": f"elara_view_{t['id']}",
            "title": f"[{st_name[:4]}] {t_title}"[:24],
            "description": f"{due_str} • {str(t.get('priority') or 'medium').capitalize()}"[:72],
        })

    sections = [{"title": f"My Tasks ({len(tasks)})", "rows": rows}]
    return send_list_message(
        to,
        f"👤 *My Assigned Tasks*\nShowing {min(10, len(tasks))} of {len(tasks)} tasks assigned to *{user_name}*:",
        "View Task Details",
        sections,
    )


def show_department_filter_menu(to: str, user: dict):
    """Display the 6 canonical Elara Home departments for filtering."""
    rows = []
    for idx, dept in enumerate(ELARA_DEPARTMENTS):
        rows.append({
            "id": f"elara_depttasks_{idx}",
            "title": dept[:24],
            "description": f"View tasks in {dept}"[:72],
        })

    sections = [{"title": "Elara 6 Departments", "rows": rows}]
    return send_list_message(
        to,
        "🏢 *Elara Home Departments*\nSelect a department to view its tasks:",
        "Select Department",
        sections,
    )


def show_projects_menu(to: str, user: dict):
    """Display list of active projects in Elara Home."""
    projects = get_projects()

    if not projects:
        buttons = [
            {"id": "elara_create_project", "title": "Create Project"},
            {"id": "elara_home", "title": "Elara Home Menu"},
        ]
        return send_interactive_buttons(
            to,
            "📁 *Elara Projects*\n\nNo projects found. Tap below to create the first project:",
            buttons,
        )

    rows = []
    for p in projects[:10]:
        rows.append({
            "id": f"elara_projtasks_{p['id']}",
            "title": p["name"][:24],
            "description": f"Dept: {p.get('department', 'General')}"[:72],
        })

    sections = [{"title": f"Active Projects ({len(projects)})", "rows": rows}]
    return send_list_message(
        to,
        f"📁 *Elara Home Projects*\nSelect a project to view its tasks:",
        "View Project Tasks",
        sections,
    )


def show_project_tasks(to: str, project_id: str, user: dict):
    """Show all tasks under a specific project."""
    project = get_project_by_id(project_id)
    proj_name = project.get("name", "Project") if project else "Project"
    tasks = get_tasks(project_id=project_id)

    if not tasks:
        buttons = [
            {"id": f"elara_addtask_proj_{project_id}", "title": "Add Task to Project"},
            {"id": "elara_projects_menu", "title": "Back to Projects"},
        ]
        return send_interactive_buttons(
            to,
            f"📁 *{proj_name}*\n\nNo tasks found in this project. Tap below to add a task:",
            buttons,
        )

    rows = []
    for t in tasks[:10]:
        status_raw = str(t.get("status") or "pending")
        st_name = STATUS_DISPLAY_NAMES.get(status_raw) or status_raw.capitalize() or "Pending"
        assignees = t.get("assigned_users") or []
        assignee_str = f"👤 {assignees[0]}" if assignees else ""
        t_title = str(t.get("title") or "Task")
        rows.append({
            "id": f"elara_view_{t['id']}",
            "title": f"[{st_name[:4]}] {t_title}"[:24],
            "description": f"{assignee_str} • {str(t.get('priority') or 'medium').capitalize()}"[:72],
        })

    sections = [{"title": f"Tasks in {proj_name[:15]}", "rows": rows}]
    return send_list_message(
        to,
        f"📁 *{proj_name}*\nShowing {min(10, len(tasks))} of {len(tasks)} tasks:",
        "View Task Details",
        sections,
    )
