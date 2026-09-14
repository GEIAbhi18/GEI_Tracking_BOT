from __future__ import annotations
import logging
from whatsapp.ux import send_text
from elara.auth import resolve_elara_user
from elara.session import get_elara_session, clear_elara_session
from elara.config import ELARA_DEPARTMENTS
from elara.db import get_task_by_id

logger = logging.getLogger(__name__)


def route_elara_message(sender: str, text: str | None = None, button_id: str | None = None,
                        user: dict | None = None, voice_transcript: str | None = None):
    """
    Central dispatcher for all Elara Home module interactions.
    """
    resolved_user = user if user is not None else resolve_elara_user(sender)

    if not resolved_user:
        send_text(sender, "You are not registered as an Elara Home team member. Please contact your administrator.")
        return

    session = get_elara_session(sender)

    # 1. Handle interactive buttons
    if button_id:
        _route_button(sender, button_id, resolved_user, session)
        return

    # 2. Handle voice transcript
    input_text = voice_transcript if voice_transcript else text
    if input_text:
        _route_text(sender, input_text, resolved_user, session)
        return


def _route_button(sender: str, button_id: str, user: dict, session: dict | None):
    """Route interactive button replies for Elara Home."""
    logger.info(f"Elara button route: {button_id} for {sender}")

    from elara.flows.home import show_elara_home
    from elara.flows.task_list import (
        show_team_tasks, show_my_tasks, show_department_filter_menu,
        show_projects_menu, show_project_tasks
    )
    from elara.flows.create_project import (
        start_create_project_flow, handle_project_department_selection,
        handle_project_description_input
    )
    from elara.flows.create_task import (
        start_create_task_flow, handle_task_project_selection,
        handle_task_priority_selection, handle_task_due_date_input
    )
    from elara.flows.task_card import send_elara_task_card
    from elara.flows.update_task import (
        start_update_task_flow, handle_status_selection, show_all_statuses
    )
    from elara.flows.comments import prompt_add_comment, show_task_comments

    # Home / Cancel
    if button_id in ("elara_home", "elara_cancel"):
        clear_elara_session(sender)
        show_elara_home(sender, user)
        return

    # Main Navigation
    if button_id == "elara_team_tasks":
        show_team_tasks(sender, user)
        return
    if button_id == "elara_my_tasks":
        show_my_tasks(sender, user)
        return
    if button_id == "elara_create_task":
        start_create_task_flow(sender, user)
        return
    if button_id == "elara_update_task":
        show_team_tasks(sender, user)
        return
    if button_id == "elara_projects_menu":
        show_projects_menu(sender, user)
        return
    if button_id == "elara_create_project":
        start_create_project_flow(sender, user)
        return
    if button_id == "elara_departments_filter":
        show_department_filter_menu(sender, user)
        return

    # View Specific Task
    if button_id.startswith("elara_view_"):
        task_id = button_id.replace("elara_view_", "")
        task = get_task_by_id(task_id)
        if task:
            send_elara_task_card(sender, task)
        else:
            send_text(sender, f"❌ Task `{task_id}` not found.")
        return

    # Task Action: Update Status
    if button_id.startswith("elara_stat_"):
        task_id = button_id.replace("elara_stat_", "")
        start_update_task_flow(sender, task_id, user)
        return

    # Task Action: Add Comment
    if button_id.startswith("elara_cmt_"):
        task_id = button_id.replace("elara_cmt_", "")
        prompt_add_comment(sender, task_id, user)
        return

    # Task Action: View Comments
    if button_id.startswith("elara_viewcmts_"):
        task_id = button_id.replace("elara_viewcmts_", "")
        show_task_comments(sender, task_id, user)
        return

    # Set Status directly
    if button_id.startswith("elara_setst_"):
        parts = button_id.replace("elara_setst_", "").split("_", 1)
        if len(parts) == 2:
            task_id, status = parts
            handle_status_selection(sender, task_id, status, user)
            return

    # Show all statuses
    if button_id.startswith("elara_morest_"):
        task_id = button_id.replace("elara_morest_", "")
        show_all_statuses(sender, task_id, user)
        return

    # Project Creation: Department Selection
    if button_id.startswith("elara_pdept_"):
        dept_idx = button_id.replace("elara_pdept_", "")
        handle_project_department_selection(sender, dept_idx, user)
        return

    if button_id == "elara_proj_skip_desc":
        handle_project_description_input(sender, "skip", user, session or {})
        return

    # Task Creation: Project Selection
    if button_id.startswith("elara_tproj_"):
        proj_id = button_id.replace("elara_tproj_", "")
        handle_task_project_selection(sender, proj_id, user, session or {})
        return

    # Task Creation: Priority Selection
    if button_id.startswith("elara_tpri_"):
        pri = button_id.replace("elara_tpri_", "")
        handle_task_priority_selection(sender, pri, user, session or {})
        return

    # Task Creation: Due Date Selection
    if button_id.startswith("elara_tdue_"):
        due_code = button_id.replace("elara_tdue_", "")
        due_map = {"tomorrow": "tomorrow", "3days": "in 3 days", "skip": "skip"}
        handle_task_due_date_input(sender, due_map.get(due_code, "skip"), user, session or {})
        return

    # Add task under specific project
    if button_id.startswith("elara_addtask_proj_"):
        proj_id = button_id.replace("elara_addtask_proj_", "")
        start_create_task_flow(sender, user, prefill={"project_id": proj_id})
        return

    # Filter tasks by department
    if button_id.startswith("elara_depttasks_"):
        dept_idx = int(button_id.replace("elara_depttasks_", ""))
        if 0 <= dept_idx < len(ELARA_DEPARTMENTS):
            show_team_tasks(sender, user, department=ELARA_DEPARTMENTS[dept_idx])
        return

    # Filter tasks by project
    if button_id.startswith("elara_projtasks_"):
        proj_id = button_id.replace("elara_projtasks_", "")
        show_project_tasks(sender, proj_id, user)
        return

    logger.warning(f"Unhandled Elara button ID: {button_id}")
    show_elara_home(sender, user)


def _route_text(sender: str, text: str, user: dict, session: dict | None):
    """Route free-text messages within Elara Home."""
    clean = text.strip().lower()

    # 1. Global navigation words
    if clean in ("hi", "hello", "hey", "menu", "start", "home", "cancel", "reset", "clear"):
        clear_elara_session(sender)
        from elara.flows.home import show_elara_home
        show_elara_home(sender, user)
        return

    # 2. Check active in-progress multi-step flow state
    state = session.get("flow_state", "") if session else ""
    session_dict = session or {}

    if state == "create_proj_name":
        from elara.flows.create_project import handle_project_name_input
        handle_project_name_input(sender, text, user, session_dict)
        return

    if state == "create_proj_desc":
        from elara.flows.create_project import handle_project_description_input
        handle_project_description_input(sender, text, user, session_dict)
        return

    if state == "create_task_title":
        from elara.flows.create_task import handle_task_title_input
        handle_task_title_input(sender, text, user, session_dict)
        return

    if state == "create_task_due_date":
        from elara.flows.create_task import handle_task_due_date_input
        handle_task_due_date_input(sender, text, user, session_dict)
        return

    if state == "task_waiting_for_comment":
        from elara.flows.comments import handle_comment_text_input
        handle_comment_text_input(sender, text, user, session_dict)
        return

    if state == "update_task_blocker_reason":
        from elara.flows.update_task import handle_blocker_reason_input
        handle_blocker_reason_input(sender, text, user, session_dict)
        return

    # 3. Direct task creation matching
    if any(clean.startswith(p) for p in ("create task", "add task", "new task", "create a task", "raise task")):
        from elara.flows.create_task import parse_task_intent_from_text, start_create_task_flow
        parsed = parse_task_intent_from_text(text, user)
        start_create_task_flow(sender, user, prefill=parsed)
        return

    # 4. Direct project creation matching
    if any(clean.startswith(p) for p in ("create project", "add project", "new project")):
        from elara.flows.create_project import start_create_project_flow
        # Check if department mentioned
        matched_dept = None
        for dept in ELARA_DEPARTMENTS:
            if dept.lower() in clean:
                matched_dept = dept
                break
        start_create_project_flow(sender, user, initial_department=matched_dept)
        return

    # 5. Direct view my tasks / team tasks matching
    if clean in ("my tasks", "my task", "show my tasks", "view my tasks"):
        from elara.flows.task_list import show_my_tasks
        show_my_tasks(sender, user)
        return

    if clean in ("tasks", "team tasks", "show tasks", "view tasks", "all tasks", "show team tasks"):
        from elara.flows.task_list import show_team_tasks
        show_team_tasks(sender, user)
        return

    if clean in ("projects", "show projects", "view projects", "all projects"):
        from elara.flows.task_list import show_projects_menu
        show_projects_menu(sender, user)
        return

    # 6. Fallback: Parse as a task creation intent if it looks like an action item
    if any(clean.startswith(p) for p in ("check ", "coordinate ", "schedule ", "inspect ", "review ", "arrange ", "call ", "submit ", "send ")):
        from elara.flows.create_task import parse_task_intent_from_text, start_create_task_flow
        parsed = parse_task_intent_from_text(text, user)
        start_create_task_flow(sender, user, prefill=parsed)
        return

    # Fallback to Elara Home menu
    from elara.flows.home import show_elara_home
    show_elara_home(sender, user)
