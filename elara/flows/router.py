from __future__ import annotations
import logging
from whatsapp.ux import send_text
from elara.auth import resolve_elara_user
from elara.session import get_elara_session, clear_elara_session
from elara.config import ELARA_DEPARTMENTS
from elara.db import get_task_by_id

logger = logging.getLogger(__name__)


def route_elara_message(sender: str, text: str | None = None, button_id: str | None = None,
                        user: dict | None = None, voice_transcript: str | None = None,
                        image_data: dict | None = None):
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

    # 2. Handle image/document attachments
    if image_data:
        route_elara_image(sender, image_data, resolved_user, session)
        return

    # 3. Handle voice transcript
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
        send_text(sender, "🔄 *Update Task*\nPlease select a task below to update its status or add comments:")
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

    # Task Action: Attach File
    if button_id.startswith("elara_attach_"):
        task_id = button_id.replace("elara_attach_", "")
        from elara.flows.attachments import prompt_attachment
        prompt_attachment(sender, task_id, user)
        return

    # Task Action: View Attachments
    if button_id.startswith("elara_viewatt_"):
        task_id = button_id.replace("elara_viewatt_", "")
        from elara.flows.attachments import show_task_attachments
        show_task_attachments(sender, task_id, user)
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

    # Task Creation: Confirm / Edit / Cancel / Assignee
    if button_id == "elara_confirm_create_task":
        from elara.flows.create_task import confirm_create_task
        confirm_create_task(sender, user, session or {})
        return

    if button_id == "elara_edit_create_task":
        from elara.flows.create_task import edit_draft_task
        edit_draft_task(sender, user, session or {})
        return

    if button_id == "elara_cancel_create_task":
        from elara.flows.create_task import cancel_create_task
        cancel_create_task(sender, user)
        return

    if button_id == "elara_tassign_keep":
        from elara.flows.create_task import show_task_draft_preview
        draft = (session or {}).get("draft", {})
        show_task_draft_preview(sender, draft, user)
        return

    if button_id == "elara_tassign_me":
        from elara.flows.create_task import show_task_draft_preview
        draft = (session or {}).get("draft", {})
        draft["assignee"] = user.get("name") or "Team Member"
        show_task_draft_preview(sender, draft, user)
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

    if state == "create_task_select_project":
        from elara.db import get_projects
        from elara.flows.create_task import handle_task_project_selection
        projects = get_projects()
        matched = None
        for p in projects:
            if clean in p["name"].lower() or p["name"].lower() in clean:
                matched = p
                break
        if matched:
            handle_task_project_selection(sender, matched["id"], user, session_dict)
        else:
            send_text(sender, "Please select a project from the list above, or type a matching project name.")
        return

    if state == "create_task_title":
        from elara.flows.create_task import handle_task_title_input
        handle_task_title_input(sender, text, user, session_dict)
        return

    if state == "create_task_due_date":
        from elara.flows.create_task import handle_task_due_date_input
        handle_task_due_date_input(sender, text, user, session_dict)
        return

    if state == "create_task_assignee":
        from elara.flows.create_task import handle_task_assignee_input
        handle_task_assignee_input(sender, text, user, session_dict)
        return

    if state == "create_task_preview":
        clean_text = text.strip().lower()
        if clean_text in ("confirm", "create", "yes", "ok", "done", "confirm & create"):
            from elara.flows.create_task import confirm_create_task
            confirm_create_task(sender, user, session_dict)
        elif clean_text in ("cancel", "stop", "abort"):
            from elara.flows.create_task import cancel_create_task
            cancel_create_task(sender, user)
        elif clean_text in ("edit", "change"):
            from elara.flows.create_task import edit_draft_task
            edit_draft_task(sender, user, session_dict)
        else:
            send_text(sender, "Please use the buttons below to *Confirm*, *Edit*, or *Cancel*.")
            from elara.flows.create_task import show_task_draft_preview
            show_task_draft_preview(sender, session_dict.get("draft", {}), user)
        return

    if state == "create_task_edit":
        from elara.flows.create_task import handle_task_edit_input
        handle_task_edit_input(sender, text, user, session_dict)
        return

    if state == "task_waiting_for_comment":
        from elara.flows.comments import handle_comment_text_input
        handle_comment_text_input(sender, text, user, session_dict)
        return

    if state == "update_task_blocker_reason":
        from elara.flows.update_task import handle_blocker_reason_input
        handle_blocker_reason_input(sender, text, user, session_dict)
        return

    if state == "attach_awaiting":
        if clean in ("cancel", "exit", "menu", "back", "no", "stop"):
            clear_elara_session(sender)
            send_text(sender, "❌ Attachment cancelled.\n\n_Type *menu* to return to Elara Home._")
        else:
            send_text(sender, "📎 Please send an image or document (PDF) in this chat to attach it to the task, or type *cancel* to return.")
        return


    # 3. Direct task creation matching
    if any(clean.startswith(p) for p in ("create task", "add task", "new task", "create a task", "raise task")):
        from elara.flows.create_task import parse_task_intent_from_text, start_create_task_flow
        parsed = parse_task_intent_from_text(text, user)
        start_create_task_flow(sender, user, prefill=parsed)
        return

    # Direct task update matching
    if any(clean.startswith(p) for p in ("update task", "task update", "update a task", "update taks")):
        from elara.flows.task_list import show_team_tasks
        send_text(sender, "🔄 *Update Task*\nPlease select a task below to update its status or add comments:")
        show_team_tasks(sender, user)
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


def route_elara_image(sender: str, image_data: dict, user: dict, session: dict | None = None) -> bool:
    """
    Handle image or document attachments for Elara Home.
    Returns True if handled.
    """
    sess = session if session is not None else get_elara_session(sender)
    state = sess.get("flow_state", "") if sess else ""

    if state.startswith("attach_"):
        draft = sess.get("draft", {}) if sess else {}
        task_id = draft.get("task_id")
        if task_id:
            from elara.flows.attachments import handle_attachment_upload
            handle_attachment_upload(sender, task_id, image_data, user)
            return True

    send_text(sender, "To attach a photo or document to an Elara Home task, first open the task card and tap *📎 Attach*.")
    return True

