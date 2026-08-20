"""
Screen 08 — Free-text Update Flow
====================================
Extract target ref no + new status + latest-update text from free text.
Show explicit before → after status change before committing.
"""

import logging

from whatsapp.ux import send_text, send_list_message, send_interactive_buttons
from facilities.sheets_client import read_row, write_field
from facilities.config import VALID_STATUSES, RAG_STATUS_MAP
from facilities.flows.router import get_session, set_session, clear_session

logger = logging.getLogger(__name__)


def start_update_flow(sender: str, ref_no: str, user: dict, prefill: dict = None):
    """Start the update flow for a specific task."""
    row = read_row(ref_no)
    if not row:
        send_text(sender, f"Task *{ref_no}* not found.")
        return

    from facilities.auth import assert_building_access
    try:
        assert_building_access(user, row.get("building", ""))
    except PermissionError as e:
        send_text(sender, f"🚫 {str(e)}")
        return

    context = {
        "ref_no": ref_no,
        "current_status": row.get("status", "Open"),
        "current_update": row.get("latest_update", ""),
    }

    if prefill and prefill.get("status"):
        # Status pre-filled from LLM — go straight to confirmation
        context["new_status"] = prefill["status"]
        context["new_update"] = prefill.get("latest_update", "")
        set_session(sender, "update_confirm", context=context)
        _show_update_preview(sender, row, context, user)
        return

    set_session(sender, "update_status", context=context)

    # Show status options as List Message
    current = row.get("status", "Open")
    rag = RAG_STATUS_MAP.get(current, {"emoji": "⚪", "label": current})

    rows = []
    for status in VALID_STATUSES:
        if status == current:
            continue
        s_rag = RAG_STATUS_MAP.get(status, {"emoji": "⚪", "label": status})
        row_title = f"{s_rag['emoji']} {status}"
        if len(row_title) > 24:
            row_title = row_title[:24]
        rows.append({"id": f"fac_status_{status}", "title": row_title})

    if not rows:
        send_text(sender, "No status transitions available for this task.")
        return

    sections = [{"title": "New Status", "rows": rows}]
    send_list_message(
        sender,
        f"🔄 *Update Task — {ref_no}*\n\n"
        f"Current status: {rag['emoji']} *{current}*\n\n"
        f"Select the new status:",
        "Select Status",
        sections,
    )


def handle_status_selection(sender: str, new_status: str, user: dict):
    """Handle status selection from the List Message."""
    session = get_session(sender)
    if not session:
        send_text(sender, "Session expired. Please try again.")
        return

    context = session.get("context_json", {})
    ref_no = context.get("ref_no")
    current_status = context.get("current_status")

    if not ref_no:
        send_text(sender, "Could not determine which task to update.")
        clear_session(sender)
        return

    # Status validation (Screen 15)
    if new_status not in VALID_STATUSES:
        from facilities.flows.status_validation import show_invalid_status
        show_invalid_status(sender, new_status, user)
        return

    # Reopen check (Screen 15)
    if current_status == "Closed" and new_status == "Open":
        from facilities.flows.status_validation import prompt_reopen_confirm
        context["new_status"] = new_status
        set_session(sender, "update_reopen_confirm", context=context)
        prompt_reopen_confirm(sender, ref_no, user)
        return

    context["new_status"] = new_status
    set_session(sender, "update_note", context=context)

    send_text(
        sender,
        f"📝 *Add a note* (optional):\n\n"
        f"Describe what was done or any update.\n"
        f"Type *skip* to proceed without a note."
    )


def handle_update_flow_text(sender: str, text: str, user: dict, session: dict):
    """Handle free-text input during the update flow."""
    state = session.get("current_flow_state", "")
    context = session.get("context_json", {})

    if state == "update_status":
        # User typed a status instead of tapping
        from rapidfuzz import fuzz, process as fuzz_process
        match = fuzz_process.extractOne(text.strip(), VALID_STATUSES, scorer=fuzz.WRatio)
        if match and match[1] >= 70:
            handle_status_selection(sender, match[0], user)
        else:
            send_text(sender, "Please select a valid status from the list.")

    elif state == "update_note":
        if text.strip().lower() in ("skip", "no", "none"):
            context["new_update"] = ""
        else:
            context["new_update"] = text.strip()

        set_session(sender, "update_confirm", context=context)

        row = read_row(context.get("ref_no"))
        _show_update_preview(sender, row, context, user)

    elif state == "update_confirm":
        send_text(sender, "Please use the buttons to *Confirm* or *Cancel* the update.")


def _show_update_preview(sender: str, row: dict, context: dict, user: dict):
    """Show before → after preview before committing."""
    ref_no = context.get("ref_no", "—")
    old_status = context.get("current_status", "—")
    new_status = context.get("new_status", "—")
    update_text = context.get("new_update", "")

    old_rag = RAG_STATUS_MAP.get(old_status, {"emoji": "⚪"})
    new_rag = RAG_STATUS_MAP.get(new_status, {"emoji": "⚪"})

    msg = (
        f"🔄 *Update Preview — {ref_no}*\n"
        f"{'─' * 25}\n\n"
        f"*Status:* {old_rag['emoji']} {old_status} → {new_rag['emoji']} {new_status}\n"
    )

    if update_text:
        msg += f"*Note:* {update_text}\n"

    msg += f"\n*Updated by:* {user.get('name', '—')}\n\nConfirm this update?"

    buttons = [
        {"id": "fac_confirm_update", "title": "✅ Confirm"},
        {"id": "fac_cancel_update", "title": "❌ Cancel"},
    ]
    send_interactive_buttons(sender, msg, buttons)

    # Also register these button handlers
    set_session(sender, "update_confirm", context=context)


def confirm_update(sender: str, user: dict):
    """Commit the update to Sheet."""
    session = get_session(sender)
    if not session:
        send_text(sender, "Session expired.")
        return

    context = session.get("context_json", {})
    ref_no = context.get("ref_no")
    new_status = context.get("new_status")
    update_text = context.get("new_update")

    if not ref_no or not new_status:
        send_text(sender, "Missing data. Please start over.")
        clear_session(sender)
        return

    actor = user.get("name")
    results = []

    # Write status
    status_result = write_field(ref_no, "status", new_status, source="gei_bot", actor=actor)
    results.append(("Status", status_result))

    # Write note if provided
    if update_text:
        note_result = write_field(ref_no, "latest_update", update_text, source="gei_bot", actor=actor)
        results.append(("Note", note_result))

    # Build response
    bot_line = "✅ *GEI_BOT:* Updated"

    all_synced = all(r[1].get("status") == "synced" for r in results)
    any_failed = any(r[1].get("status") == "failed" for r in results)
    any_conflict = any(r[1].get("status") == "conflict" for r in results)

    if all_synced:
        sheet_line = "✅ *Google Sheets:* Synced"
    elif any_conflict:
        sheet_line = "⚠️ *Google Sheets:* Conflict detected — please resolve"
    elif any_failed:
        sheet_line = "⏳ *Google Sheets:* Sync Pending — auto-retrying"
    else:
        sheet_line = "⏳ *Google Sheets:* Processing"

    old_rag = RAG_STATUS_MAP.get(context.get("current_status"), {"emoji": "⚪"})
    new_rag = RAG_STATUS_MAP.get(new_status, {"emoji": "⚪"})

    msg = (
        f"✅ *Task Updated — {ref_no}*\n\n"
        f"*Status:* {old_rag['emoji']} {context.get('current_status')} → {new_rag['emoji']} {new_status}\n"
    )
    if update_text:
        msg += f"*Note:* {update_text}\n"

    msg += f"\n{bot_line}\n{sheet_line}"

    send_text(sender, msg)
    clear_session(sender)


def prompt_ref_no_for_update(sender: str, user: dict):
    """Ask the user for a Ref No to update."""
    set_session(sender, "update_ref_no_input")

    send_text(
        sender,
        "🔄 *Update Task*\n\n"
        "Please provide the Ref No of the task you want to update.\n"
        "(e.g., *GEBB1-001*, *GETT-042*)"
    )
