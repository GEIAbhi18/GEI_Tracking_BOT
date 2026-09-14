from __future__ import annotations
from whatsapp.ux import send_list_message, send_interactive_buttons
from elara.auth import is_elara_admin


def show_elara_home(to: str, user: dict):
    """Display the main menu and greeting for Elara Home."""
    user_name = user.get("name", "Team Member")
    user_role = user.get("role", "Member")
    dept = user.get("department") or "All Departments"

    body = (
        f"🏠 *Elara Home — TaskFlow*\n"
        f"Hello *{user_name}* ({user_role})\n"
        f"Department: _{dept}_\n\n"
        f"What would you like to do today?"
    )

    task_rows = [
        {"id": "elara_team_tasks", "title": "📋 Team Tasks", "description": "View active Elara Home tasks"},
        {"id": "elara_my_tasks", "title": "👤 My Tasks", "description": "View tasks assigned to you"},
        {"id": "elara_create_task", "title": "➕ Create Task", "description": "Add a new task in Kanban"},
        {"id": "elara_update_task", "title": "🔄 Update Task", "description": "Update status, progress or notes"},
    ]

    project_rows = [
        {"id": "elara_projects_menu", "title": "📁 View Projects", "description": "Browse all active projects"},
        {"id": "elara_create_project", "title": "✨ Create Project", "description": "Create a new project in Kanban"},
        {"id": "elara_departments_filter", "title": "🏢 6 Departments", "description": "Filter tasks by department"},
    ]

    sections = [
        {"title": "Tasks Management", "rows": task_rows},
        {"title": "Projects & Departments", "rows": project_rows},
    ]

    # For Director (Kanav) and Developer, allow switching back to Facilities
    if is_elara_admin(user):
        admin_rows = [
            {"id": "team_sel_facilities", "title": "🏢 Facilities Team", "description": "Switch context to Facilities"},
            {"id": "team_sel_prompt", "title": "🔀 Select Team", "description": "Choose between Facilities & Elara"},
        ]
        sections.append({"title": "Team Switcher", "rows": admin_rows})

    return send_list_message(to, body, "Open Menu", sections)
