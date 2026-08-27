"""
Screen 05/06/07 — Conversational Task Creation
=================================================
Uses Claude to extract entities from free text.
Only asks for genuinely missing fields.
Type prompt as List Message (4 options).
Draft preview before any write.
Confirm & Create / Edit / Cancel as Reply Buttons (3 options).
On confirm: creates row, reports two separate status lines.
"""

import logging

from whatsapp.ux import send_text, send_list_message, send_interactive_buttons
from facilities.auth import assert_building_access, get_permitted_buildings, fuzzy_match_building
from facilities.config import VALID_TASK_TYPES, VALID_STATUSES
from facilities.flows.router import get_session, set_session, clear_session

logger = logging.getLogger(__name__)


def start_create_flow(sender: str, user: dict, prefill: dict = None):
    """Start the task creation flow. Pre-fill from LLM extraction if available."""
    from facilities.sheets_client import _format_sheet_date, normalize_owner_to_sheet_position
    draft = {
        "building": None,
        "type": None,
        "issue_action": None,
        "owner": normalize_owner_to_sheet_position(user.get("role", "") or user.get("name", "")),
        "target_date": None,
        "status": "Open",
    }

    # Apply prefill from LLM
    if prefill:
        for key in draft:
            if prefill.get(key):
                draft[key] = prefill[key]
        if draft.get("target_date"):
            draft["target_date"] = _format_sheet_date(str(draft["target_date"]))
        if draft.get("owner"):
            draft["owner"] = normalize_owner_to_sheet_position(str(draft["owner"]), draft.get("building"))

    set_session(sender, "create_building", draft=draft, context={"next_action": "create_task"})

    # Check what's already filled
    if draft["building"] and draft["type"] and draft["issue_action"]:
        # All mandatory fields present — skip to preview
        _show_draft_preview(sender, draft, user)
        return

    if draft["building"]:
        # Building known — ask for type next
        _prompt_type(sender, user)
        return

    # Ask for building
    _prompt_building(sender, user)


def _prompt_building(sender: str, user: dict):
    """Ask for building selection."""
    buildings = get_permitted_buildings(user)

    if len(buildings) <= 3:
        # Use Reply Buttons
        buttons = [{"id": f"fac_bldg_{b}", "title": b} for b in buildings]
        send_interactive_buttons(
            sender,
            "➕ *Create New Task*\n\nWhich building is this task for?",
            buttons,
        )
    else:
        # Use List Message
        rows = [{"id": f"fac_bldg_{b}", "title": b} for b in buildings]
        sections = [{"title": "Select Building", "rows": rows}]
        send_list_message(
            sender,
            "➕ *Create New Task*\n\nWhich building is this task for?",
            "Select Building",
            sections,
        )


def handle_building_selection(sender: str, building: str, user: dict):
    """Handle building selection during create flow."""
    session = get_session(sender)
    if not session:
        start_create_flow(sender, user)
        return

    draft = session.get("draft_task_json", {})
    draft["building"] = building
    set_session(sender, "create_type", draft=draft, context={"next_action": "create_task"})

    # If type and issue_action were already prefilled (e.g. from conversational command), go straight to preview
    if draft.get("type") and draft.get("issue_action"):
        _show_draft_preview(sender, draft, user)
    elif draft.get("type"):
        set_session(sender, "create_issue", draft=draft, context={"next_action": "create_task"})
        send_text(
            sender,
            f"📝 *Describe the issue/action:*\n\n"
            f"Type the task description for *{building}*. Be specific about the location and what needs to be done."
        )
    else:
        _prompt_type(sender, user)


def _prompt_type(sender: str, user: dict):
    """Ask for task type (List Message matching Google Sheet Types)."""
    type_display = {
        "Project": "📁 Project",
        "Client Escalation": "🚨 Client Escalation",
        "Management Discussion": "🗣️ Mgmt Discussion",
        "Improvement / Initiative": "💡 Improvement/Initiative",
        "Major Concern": "⚠️ Major Concern",
        "Other": "📌 Other",
    }
    rows = [
        {"id": f"fac_type_{t}", "title": type_display.get(t, t)[:24]} for t in VALID_TASK_TYPES
    ]
    sections = [{"title": "Select Task Type", "rows": rows}]
    send_list_message(
        sender,
        "What type of task is this?",
        "Select Type",
        sections,
    )


def handle_type_selection(sender: str, task_type: str, user: dict):
    """Handle type selection during create flow."""
    session = get_session(sender)
    if not session:
        start_create_flow(sender, user)
        return

    draft = session.get("draft_task_json", {})
    draft["type"] = task_type

    # If issue_action was already prefilled from conversational input, advance to next missing field
    if draft.get("issue_action"):
        if draft.get("target_date") and draft.get("owner"):
            _show_draft_preview(sender, draft, user)
            return
        elif not draft.get("target_date"):
            set_session(sender, "create_target_date", draft=draft, context={"next_action": "create_task"})
            send_text(
                sender,
                "📅 *Target Date:*\n\n"
                "When should this be completed?\n"
                "(e.g., *tomorrow*, *next Friday*, *2026-09-15*, or *skip* for no date)"
            )
            return
        else:
            set_session(sender, "create_owner", draft=draft, context={"next_action": "create_task"})
            send_text(
                sender,
                f"👤 *Owner:*\n\n"
                f"Who should this be assigned to?\n"
                f"(Currently set to: *{draft.get('owner', 'you')}*)\n\n"
                f"Type a name, or type *me* to keep it assigned to yourself."
            )
            return

    set_session(sender, "create_issue", draft=draft, context={"next_action": "create_task"})

    send_text(
        sender,
        f"📝 *Describe the issue/action:*\n\n"
        f"Type the task description. Be specific about the location and what needs to be done."
    )


def handle_create_flow_text(sender: str, text: str, user: dict, session: dict):
    """Handle free-text input during the create flow."""
    state = session.get("current_flow_state", "")
    draft = session.get("draft_task_json", {})

    if state == "create_building":
        # If user sent a full sentence (e.g. "Create task for bay 1..."), extract all entities
        if len(text.strip().split()) > 2 or any(w in text.lower() for w in ["task", "issue", "create", "assign", "for", "due", "manager", "head"]):
            from facilities.llm import extract_intent
            result = extract_intent(text)
            if result and result.get("intents"):
                extracted = result["intents"][0].get("entities", {})
                for k in ("building", "type", "issue_action", "owner", "target_date"):
                    if extracted.get(k):
                        draft[k] = extracted[k]

        # If building is not set, try direct fuzzy matching
        if not draft.get("building"):
            bldg = fuzzy_match_building(text)
            if bldg:
                draft["building"] = bldg

        if draft.get("building"):
            try:
                assert_building_access(user, draft["building"])
            except PermissionError as e:
                send_text(sender, f"🚫 {str(e)}")
                return

            if draft.get("type") and draft.get("issue_action"):
                _show_draft_preview(sender, draft, user)
                return
            elif draft.get("type"):
                set_session(sender, "create_issue", draft=draft, context={"next_action": "create_task"})
                send_text(
                    sender,
                    f"📝 *Describe the issue/action:*\n\n"
                    f"Type the task description for *{draft['building']}*. Be specific about the location and what needs to be done."
                )
                return
            else:
                set_session(sender, "create_type", draft=draft, context={"next_action": "create_task"})
                _prompt_type(sender, user)
                return

        # Show "did you mean" (Screen 13)
        from facilities.flows.building_filter import show_did_you_mean
        show_did_you_mean(sender, text, user)

    elif state == "create_type":
        # Try to match to a valid type
        from rapidfuzz import fuzz, process as fuzz_process
        match = fuzz_process.extractOne(text.strip(), VALID_TASK_TYPES, scorer=fuzz.WRatio)
        if match and match[1] >= 70:
            handle_type_selection(sender, match[0], user)
        else:
            send_text(sender, "Please select a valid task type from the list.")
            _prompt_type(sender, user)

    elif state == "create_issue":
        clean_text = text.strip()
        import re
        m = re.search(r'\b(?:created by|by|done by|assigned to|for)\s+([A-Za-z]+)\b', clean_text, re.IGNORECASE)
        if m:
            person = m.group(1).lower()
            if person in ("kanav", "kk", "director"):
                draft["owner"] = "Facilities Director"
                clean_text = re.sub(r'\s*(?:created by|by|done by|assigned to|for)\s+[A-Za-z]+["\']?\s*$', '', clean_text, flags=re.IGNORECASE).strip()
            elif person in ("anoop", "head"):
                draft["owner"] = "Facility Head"
                clean_text = re.sub(r'\s*(?:created by|by|done by|assigned to|for)\s+[A-Za-z]+["\']?\s*$', '', clean_text, flags=re.IGNORECASE).strip()
            elif person in ("vikram", "vikramjeet", "vikash", "fm", "manager"):
                draft["owner"] = "Facility Manager"
                clean_text = re.sub(r'\s*(?:created by|by|done by|assigned to|for)\s+[A-Za-z]+["\']?\s*$', '', clean_text, flags=re.IGNORECASE).strip()

        draft["issue_action"] = clean_text or text.strip()
        set_session(sender, "create_target_date", draft=draft, context={"next_action": "create_task"})
        send_text(
            sender,
            "📅 *Target Date:*\n\n"
            "When should this be completed?\n"
            "(e.g., *tomorrow*, *next Friday*, *2026-09-15*, or *skip* for no date)"
        )

    elif state == "create_target_date":
        if text.strip().lower() in ("skip", "no", "none", "na", "-", "—"):
            draft["target_date"] = "—"
        else:
            from core.utils import parse_human_date
            parsed = parse_human_date(text)
            draft["target_date"] = parsed if parsed else text.strip()

        set_session(sender, "create_owner", draft=draft, context={"next_action": "create_task"})

        current_owner = draft.get("owner") or "Facility Manager"
        send_text(
            sender,
            f"👤 *Owner:*\n\n"
            f"Who should this be assigned to?\n"
            f"(Currently set to: *{current_owner}*)\n\n"
            f"Type a name (e.g. *Kanav*, *Anoop*, *Vikramjeet*), or type *me* to assign to yourself."
        )

    elif state == "create_owner":
        from facilities.sheets_client import normalize_owner_to_sheet_position
        if text.strip().lower() in ("me", "myself", "self"):
            draft["owner"] = normalize_owner_to_sheet_position(user.get("role", "") or user.get("name", ""), draft.get("building"))
        else:
            draft["owner"] = normalize_owner_to_sheet_position(text.strip(), draft.get("building"))

        _show_draft_preview(sender, draft, user)

    elif state == "create_preview":
        # User typed something during preview — treat as edit
        from facilities.llm import extract_intent
        result = extract_intent(text, context={"current_draft": draft})
        # For now, just show the preview again
        send_text(sender, "Please use the buttons below to *Confirm*, *Edit*, or *Cancel*.")

    else:
        # Unknown state — restart
        clear_session(sender)
        start_create_flow(sender, user)


def _show_draft_preview(sender: str, draft: dict, user: dict):
    """Show the draft preview card before creating."""
    set_session(sender, "create_preview", draft=draft)

    # Check for duplicates first (Screen 14)
    _check_and_show_preview(sender, draft, user)


def _check_and_show_preview(sender: str, draft: dict, user: dict,
                              skip_duplicate: bool = False):
    """Check for duplicates, then show preview."""
    building = draft.get("building", "")

    if not skip_duplicate and building:
        from facilities.llm import check_duplicate
        from facilities.sheets_client import list_rows_by_building

        open_tasks = [
            t for t in list_rows_by_building(building)
            if t.get("status") in ("Open", "WIP", "Escalated")
        ]

        duplicate = check_duplicate(building, draft.get("issue_action", ""), open_tasks)

        if duplicate:
            # Show duplicate detection (Screen 14)
            dup_ref = duplicate.get("ref_no", "—")
            dup_issue = duplicate.get("issue_action", "")
            reason = duplicate.get("similarity_reason", "")

            msg = (
                f"⚠️ *Possible Duplicate Detected*\n\n"
                f"Your new task:\n"
                f"_{draft.get('issue_action', '')}_\n\n"
                f"Similar existing task:\n"
                f"*{dup_ref}*: _{dup_issue}_\n"
                f"_{reason}_\n\n"
                f"Would you like to update the existing task or create a new one?"
            )

            buttons = [
                {"id": f"fac_update_existing_{dup_ref}", "title": "Update Existing"},
                {"id": "fac_create_anyway", "title": "Create New"},
            ]
            send_interactive_buttons(sender, msg, buttons)
            return

    # No duplicate — show preview
    from facilities.sheets_client import _format_sheet_date
    target_date_disp = _format_sheet_date(draft.get('target_date', '')) or draft.get('target_date') or '—'
    preview = (
        f"📝 *Task Draft — Review*\n"
        f"{'─' * 25}\n\n"
        f"🏗️ *Building:* {draft.get('building', '—')}\n"
        f"📁 *Type:* {draft.get('type', '—')}\n"
        f"🔧 *Issue/Action:* {draft.get('issue_action', '—')}\n"
        f"👤 *Owner:* {draft.get('owner', '—')}\n"
        f"📅 *Target Date:* {target_date_disp}\n"
        f"🔴 *Status:* Open\n\n"
        f"Please confirm to create this task."
    )

    buttons = [
        {"id": "fac_confirm_create", "title": "✅ Confirm & Create"},
        {"id": "fac_edit_draft", "title": "✏️ Edit"},
        {"id": "fac_cancel_create", "title": "❌ Cancel"},
    ]
    send_interactive_buttons(sender, preview, buttons)


def confirm_create(sender: str, user: dict, skip_duplicate_check: bool = False):
    """Confirm and create the task (Screen 07)."""
    session = get_session(sender)
    if not session:
        send_text(sender, "Session expired. Please start over.")
        return

    draft = session.get("draft_task_json", {})

    if not skip_duplicate_check:
        # Re-show preview with duplicate check if needed
        pass

    building = draft.get("building")
    if not building:
        send_text(sender, "Missing building. Please start over.")
        clear_session(sender)
        return

    # Create the row
    from facilities.sheets_client import create_row
    result = create_row(building, draft, actor=user.get("name"))

    ref_no = result.get("ref_no", "—")
    sheet_status = result.get("sheet_status", "failed")

    # Build the response (two separate status lines)
    bot_line = "✅ *GEI_BOT:* Task Created"
    if sheet_status == "synced":
        sheet_line = "✅ *Google Sheets:* Updated"
    else:
        sheet_line = "⏳ *Google Sheets:* Sync Pending — auto-retrying"

    msg = (
        f"🎉 *Task Created Successfully!*\n\n"
        f"*Ref No:* {ref_no}\n"
        f"🏗️ {draft.get('building', '—')} | 📁 {draft.get('type', '—')}\n"
        f"🔧 {draft.get('issue_action', '—')}\n\n"
        f"{bot_line}\n"
        f"{sheet_line}"
    )

    send_text(sender, msg)
    clear_session(sender)


def edit_draft(sender: str, user: dict):
    """Go back to editing the draft."""
    session = get_session(sender)
    if not session:
        start_create_flow(sender, user)
        return

    draft = session.get("draft_task_json", {})
    set_session(sender, "create_building", draft=draft)

    send_text(
        sender,
        "✏️ *Edit Draft*\n\n"
        "Which field would you like to change? "
        "Just type the new value with the field name, e.g.:\n"
        "• *Building: GEBB2*\n"
        "• *Type: Electrical*\n"
        "• *Owner: Kuldeep*\n\n"
        "Or type *preview* to see the draft again."
    )


def cancel_create(sender: str, user: dict):
    """Cancel task creation."""
    clear_session(sender)
    send_text(sender, "❌ Task creation cancelled.\n\n_Type *menu* to go back._")
