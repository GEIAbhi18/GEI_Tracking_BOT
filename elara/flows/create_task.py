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
from core.utils import parse_human_date, format_date_human

logger = logging.getLogger(__name__)


def parse_task_intent_from_text(text: str, user: dict) -> dict:
    """
    Extract title, project/dept, priority, due date, and assignee from natural language.
    Examples:
      - "Create task for puja to speak to Nikhil Kumar about open points"
      - "Create task for puja to speak to Nikhil Kumar about open points due tomorrow"
      - "Create task: inspect site 2 assigned to Gaurav due 2026-09-25 priority high"
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

    # 1. Priority extraction
    if re.search(r'\b(urgent|critical|high priority|priority high)\b', clean, re.I):
        entities["priority"] = "high"
    elif re.search(r'\b(low priority|priority low)\b', clean, re.I):
        entities["priority"] = "low"
    elif re.search(r'\b(medium priority|priority medium)\b', clean, re.I):
        entities["priority"] = "medium"

    # 2. Department detection from 6 canonical Elara departments
    for dept in ELARA_DEPARTMENTS:
        if dept.lower() in clean.lower():
            # pyrefly: ignore [bad-assignment]
            entities["department"] = dept
            break

    # 3. Date extraction (e.g., "due tomorrow", "by Friday", "due 2026-09-20")
    date_match = re.search(r'\b(?:due(?:\s+on)?|by|deadline)\s+([a-zA-Z0-9\s\-]+?)(?:\s+(?:priority|for|under|assigned)|\s*$)', clean, re.I)
    if date_match:
        raw_date_str = date_match.group(1).strip()
        parsed = parse_human_date(raw_date_str)
        if parsed:
            entities["due_date"] = parsed
    if not entities["due_date"]:
        for dw in ("tomorrow", "in 3 days", "next monday", "next friday"):
            if dw in clean.lower():
                parsed = parse_human_date(dw)
                if parsed:
                    entities["due_date"] = parsed
                    break

    # 4. Assignee & Title extraction
    # Pattern A: "create task for <person> to <action>" or "create task for <person>: <action>"
    m_action = re.search(
        r'^(?:please\s+)?(?:create|add|new|raise)\s+(?:a\s+)?(?:task|elara task)\s*(?:to|for)\s+([A-Za-z]+)\s*(?:to|:)\s*(.+)$',
        clean,
        re.I
    )
    if m_action:
        entities["assignee"] = m_action.group(1).capitalize()
        title = m_action.group(2).strip()
    else:
        # Pattern B: "assigned to <person>" or "assign to <person>"
        m_for = re.search(r'\b(?:assigned to|assign to)\s+([A-Za-z]+)\b', clean, re.I)
        if m_for:
            entities["assignee"] = m_for.group(1).capitalize()
        else:
            # Check against known team members
            team_members = get_elara_team_members()
            for m in team_members:
                name = m.get("name", "")
                if name and re.search(rf'\b(?:for|to|assign(?:ed)? to)\s+{re.escape(name)}\b', clean, re.I):
                    entities["assignee"] = name
                    break
                elif name and name.lower() in clean.lower() and len(name) > 2:
                    entities["assignee"] = name

        title = clean
        # Strip trigger words
        title = re.sub(r'^(?:please\s+)?(?:create|add|new|raise)\s+(?:a\s+)?(?:task|elara task)\s*(?:to|for|called|named|:)?\s*', '', title, flags=re.I)
        assignee_val = entities.get("assignee")
        if assignee_val:
            title = re.sub(r'\b(?:assigned to|assign to|for)\s+' + re.escape(assignee_val) + r'\b', '', title, flags=re.I).strip()

    # Clean trailing priority/due/dept clauses from title
    title = re.sub(r'\s+(?:priority\s+\w+|due\s+.*|by\s+.*|deadline\s+.*|assigned\s+to\s+.*)$', '', title, flags=re.I).strip()
    for dept in ELARA_DEPARTMENTS:
        title = re.sub(r'\s+(?:for|in|under)\s+' + re.escape(dept), '', title, flags=re.I).strip()

    if title:
        entities["title"] = title[0].upper() + title[1:] if len(title) > 1 else title.upper()

    return entities


def start_create_task_flow(to: str, user: dict, prefill: dict | None = None):
    """
    Start task creation with a guided flow matching Facilities:
    Project -> Title -> Priority (if missing) -> Due Date (if missing) -> Assignee Confirmation -> Draft Preview Card -> Confirm & Create.
    """
    draft = prefill.copy() if prefill else {}

    # If project not known, see if department is known or user belongs to a specific department
    project_id = draft.get("project_id")
    if not project_id and draft.get("department"):
        dept_projects = get_projects(draft["department"])
        if dept_projects:
            project_id = dept_projects[0]["id"]
            draft["project_id"] = project_id

    if not project_id and not is_elara_admin(user) and user.get("department"):
        user_dept = user.get("department")
        dept_projects = get_projects(user_dept)
        if dept_projects:
            project_id = dept_projects[0]["id"]
            draft["project_id"] = project_id
            draft["department"] = user_dept

    # 1. Project missing -> prompt project selection list
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

    # 2. Title missing -> prompt title
    if not draft.get("title"):
        return prompt_task_title(to, draft)

    # 3. Due date missing -> prompt due date
    if not draft.get("due_date"):
        return prompt_task_due_date(to, draft)

    # 4. Assignee confirmation
    return prompt_task_assignee(to, draft, user)


def prompt_task_title(to: str, draft: dict):
    """Prompt user to enter the task title."""
    set_elara_session(to, "create_task_title", draft=draft)
    proj_id = draft.get("project_id")
    proj = get_project_by_id(proj_id) if proj_id else {}
    if not isinstance(proj, dict):
        proj = {}
    proj_name = proj.get("name", "Project")
    return send_text(
        to,
        f"➕ Creating task under *{proj_name}*.\n\n"
        f"Please enter the *Task Title*:"
    )


def handle_task_project_selection(to: str, project_id: str, user: dict, session: dict | None = None):
    """Handle project selection for task creation."""
    draft = (session or {}).get("draft", {})
    draft["project_id"] = project_id
    proj = get_project_by_id(project_id) if project_id else {}
    if isinstance(proj, dict) and proj.get("department"):
        draft["department"] = proj.get("department")

    if not draft.get("title"):
        return prompt_task_title(to, draft)

    if not draft.get("due_date"):
        return prompt_task_due_date(to, draft)

    return prompt_task_assignee(to, draft, user)


def handle_task_title_input(to: str, text: str, user: dict, session: dict | None = None):
    """Receive task title and prompt priority or due date."""
    clean_title = text.strip()
    if not clean_title:
        return send_text(to, "Please enter a valid Task Title:")

    draft = (session or {}).get("draft", {})
    draft["title"] = clean_title

    # Prompt priority
    return prompt_task_priority(to, draft)


def prompt_task_priority(to: str, draft: dict):
    """Prompt user to select task priority."""
    set_elara_session(to, "create_task_priority", draft=draft)
    buttons = [
        {"id": "elara_tpri_medium", "title": "Medium Priority"},
        {"id": "elara_tpri_high", "title": "High Priority"},
        {"id": "elara_tpri_low", "title": "Low Priority"},
    ]
    return send_interactive_buttons(
        to,
        f"Task: *{draft.get('title', 'Task')}*\n\nSelect task priority:",
        buttons,
    )


def handle_task_priority_selection(to: str, priority: str, user: dict, session: dict | None = None):
    """Receive task priority and advance to due date or assignee."""
    draft = (session or {}).get("draft", {})
    draft["priority"] = priority.lower() if priority in VALID_PRIORITIES else "medium"

    if not draft.get("due_date"):
        return prompt_task_due_date(to, draft)

    return prompt_task_assignee(to, draft, user)


def prompt_task_due_date(to: str, draft: dict):
    """Prompt user to specify or confirm the due date."""
    set_elara_session(to, "create_task_due_date", draft=draft)
    buttons = [
        {"id": "elara_tdue_tomorrow", "title": "Tomorrow"},
        {"id": "elara_tdue_3days", "title": "In 3 Days"},
        {"id": "elara_tdue_skip", "title": "Skip Due Date"},
    ]
    return send_interactive_buttons(
        to,
        f"📅 *Due Date — {draft.get('title', 'Task')}*\n\n"
        f"When is this task due? You can tap an option below or type a date (e.g. *tomorrow*, *next Monday*, *Sep 25*):",
        buttons,
    )


def handle_task_due_date_input(to: str, text: str, user: dict, session: dict | None = None):
    """Receive task due date input and prompt assignee confirmation."""
    draft = (session or {}).get("draft", {})
    clean_text = text.strip().lower()

    if clean_text in ("skip", "skip due date", "none", "no", "skip date", "na", "-"):
        draft["due_date"] = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    elif clean_text == "tomorrow":
        draft["due_date"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    elif clean_text in ("in 3 days", "3 days"):
        draft["due_date"] = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    else:
        parsed = parse_human_date(clean_text)
        if parsed:
            draft["due_date"] = parsed
        else:
            draft["due_date"] = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()

    return prompt_task_assignee(to, draft, user)


def prompt_task_assignee(to: str, draft: dict, user: dict):
    """Prompt user to confirm or specify the assignee for the task."""
    set_elara_session(to, "create_task_assignee", draft=draft)
    current_assignee = draft.get("assignee")
    user_name = user.get("name") or "Team Member"

    if current_assignee:
        body = (
            f"👤 *Assignee — {draft.get('title', 'Task')}*\n\n"
            f"Who should this task be assigned to?\n"
            f"(Currently set to: *{current_assignee}*)\n\n"
            f"Type a name (e.g. *Puja*, *Gaurav*, *Rachit*), or type *me* to assign to yourself, or tap an option below:"
        )
        keep_title = f"Keep {current_assignee}"
        if len(keep_title) > 20:
            keep_title = keep_title[:20]
        buttons = [
            {"id": "elara_tassign_keep", "title": keep_title},
            {"id": "elara_tassign_me", "title": "Assign to Me"},
        ]
    else:
        body = (
            f"👤 *Assignee — {draft.get('title', 'Task')}*\n\n"
            f"Who should this task be assigned to?\n"
            f"(Default: *{user_name}*)\n\n"
            f"Type a name (e.g. *Puja*, *Gaurav*, *Rachit*), or type *me* to assign to yourself."
        )
        buttons = [
            {"id": "elara_tassign_me", "title": "Assign to Me"},
        ]

    return send_interactive_buttons(to, body, buttons)


def handle_task_assignee_input(to: str, text: str, user: dict, session: dict | None = None):
    """Receive task assignee input and show draft preview."""
    draft = (session or {}).get("draft", {})
    clean = text.strip()
    clean_lower = clean.lower()
    current_assignee = draft.get("assignee")

    if clean_lower in ("me", "myself", "self", "assign to me"):
        draft["assignee"] = user.get("name") or "Team Member"
    elif clean_lower in ("keep", "skip", "ok", "yes", "current") and current_assignee:
        draft["assignee"] = current_assignee
    else:
        draft["assignee"] = clean.title()

    return show_task_draft_preview(to, draft, user)


def show_task_draft_preview(to: str, draft: dict, user: dict):
    """Show the draft preview review card before creating (aligned with Facilities Screen 07)."""
    set_elara_session(to, "create_task_preview", draft=draft)

    proj_id = draft.get("project_id")
    proj = get_project_by_id(proj_id) if proj_id else {}
    if not isinstance(proj, dict):
        proj = {}
    proj_name = proj.get("name", "Project")
    dept_name = proj.get("department") or draft.get("department") or "General"

    title = draft.get("title", "—")
    priority = (draft.get("priority") or "medium").capitalize()
    assignee = draft.get("assignee") or user.get("name", "Team Member")

    raw_date = draft.get("due_date")
    if raw_date:
        date_formatted = format_date_human(raw_date)
        due_disp = f"{date_formatted} ({str(raw_date)[:10]})" if date_formatted else str(raw_date)[:10]
    else:
        due_disp = "—"

    preview = (
        f"📝 *Elara Task Draft — Review*\n"
        f"{'─' * 25}\n\n"
        f"📁 *Project:* {proj_name} ({dept_name})\n"
        f"📌 *Task Title:* {title}\n"
        f"🎯 *Priority:* {priority}\n"
        f"👤 *Assignee:* {assignee}\n"
        f"📅 *Due Date:* {due_disp}\n"
        f"⏳ *Status:* Pending\n\n"
        f"Please confirm to create this task."
    )

    buttons = [
        {"id": "elara_confirm_create_task", "title": "✅ Confirm & Create"},
        {"id": "elara_edit_create_task", "title": "✏️ Edit"},
        {"id": "elara_cancel_create_task", "title": "❌ Cancel"},
    ]
    return send_interactive_buttons(to, preview, buttons)


def confirm_create_task(to: str, user: dict, session: dict | None = None):
    """Confirm and finalize the task creation."""
    draft = (session or {}).get("draft", {})
    return finalize_task_creation(to, user, draft)


def edit_draft_task(to: str, user: dict, session: dict | None = None):
    """Allow user to edit fields in the draft."""
    draft = (session or {}).get("draft", {})
    set_elara_session(to, "create_task_edit", draft=draft)
    return send_text(
        to,
        "✏️ *Edit Elara Task Draft*\n\n"
        "Which field would you like to change? Just type the field name and new value, e.g.:\n"
        "• *Title: Speak to Nikhil Kumar*\n"
        "• *Assignee: Puja*\n"
        "• *Due: 2026-09-25* (or *tomorrow*)\n"
        "• *Priority: High*\n\n"
        "Or type *preview* to review the draft again."
    )


def handle_task_edit_input(to: str, text: str, user: dict, session: dict | None = None):
    """Handle text input during draft edit mode."""
    draft = (session or {}).get("draft", {})
    clean = text.strip()
    clean_lower = clean.lower()

    if clean_lower in ("preview", "back", "show", "review"):
        return show_task_draft_preview(to, draft, user)

    if ":" in clean:
        field, val = clean.split(":", 1)
        field = field.strip().lower()
        val = val.strip()

        if field in ("title", "task", "name"):
            draft["title"] = val
        elif field in ("assignee", "owner", "assigned to", "for"):
            draft["assignee"] = val.title()
        elif field in ("due", "due date", "date", "deadline"):
            parsed = parse_human_date(val)
            draft["due_date"] = parsed if parsed else val
        elif field in ("priority", "pri"):
            draft["priority"] = val.lower() if val.lower() in VALID_PRIORITIES else "medium"
        elif field in ("project", "dept", "department"):
            projects = get_projects()
            for p in projects:
                if val.lower() in p["name"].lower():
                    draft["project_id"] = p["id"]
                    draft["department"] = p.get("department")
                    break
    else:
        if clean_lower in ("high", "medium", "low"):
            draft["priority"] = clean_lower
        elif parse_human_date(clean):
            draft["due_date"] = parse_human_date(clean)
        else:
            draft["title"] = clean

    return show_task_draft_preview(to, draft, user)


def cancel_create_task(to: str, user: dict):
    """Cancel task creation."""
    clear_elara_session(to)
    return send_text(to, "❌ Task creation cancelled.\n\n_Type *menu* to go back to Elara Home._")


def _notify_elara_assignee(task: dict, assignee_name: str, creator_name: str, project_name: str):
    """Notify the assigned Elara user via WhatsApp if they have a phone number registered."""
    try:
        if not assignee_name or assignee_name.lower() == creator_name.lower():
            return
        from db import supabase
        from whatsapp.ux import send_text

        wa = None
        # Check elara_users table first
        res = supabase.table("elara_users").select("phone, name").ilike("name", f"%{assignee_name}%").execute()
        if res.data and res.data[0].get("phone"):
            wa = res.data[0]["phone"]
        else:
            # Check general users table
            res2 = supabase.table("users").select("whatsapp_number, name").ilike("name", f"%{assignee_name}%").execute()
            if res2.data and res2.data[0].get("whatsapp_number"):
                wa = res2.data[0]["whatsapp_number"]


        if wa:
            from clients.config import TREAT_CHAITANYA_AS_TENANT_ONLY, is_chaitanya

            if TREAT_CHAITANYA_AS_TENANT_ONLY and is_chaitanya(wa):
                return
            task_title = task.get("title", "Task")
            due_date = str(task.get("due_date", "—"))[:10]
            msg = (
                f"📋 *Elara Task Assigned to You*\n\n"
                f"*{task_title}* has been assigned to you by *{creator_name}*.\n"
                f"📁 Project: {project_name}\n"
                f"📅 Due Date: {due_date}\n\n"
                f"Open Elara Home to view details and update progress."
            )
            send_text(wa, msg)
            logger.info(f"Notified Elara assignee {assignee_name} ({wa}) for task {task.get('id')}")
    except Exception as e:
        logger.warning(f"Could not notify Elara assignee {assignee_name}: {e}")


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

    # Notify assignee if different from creator
    proj = get_project_by_id(project_id)
    proj_name = proj.get("name", "Elara Project") if proj else "Elara Project"
    _notify_elara_assignee(created_task, assignee, creator_name, proj_name)

    clear_elara_session(to)
    send_text(to, "✅ *Elara Task Created Successfully!*")
    return send_elara_task_card(to, created_task)
