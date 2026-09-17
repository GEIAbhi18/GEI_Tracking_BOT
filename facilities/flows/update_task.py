"""
Screen 08 — Free-text Update Flow
====================================
Extract target ref no + new status + latest-update text from free text.
Show explicit before → after status change before committing.
"""

from __future__ import annotations
import logging

from whatsapp.ux import send_text, send_list_message, send_interactive_buttons
from facilities.sheets_client import read_row, write_field
from facilities.config import VALID_STATUSES, RAG_STATUS_MAP
from facilities.flows.router import get_session, set_session, clear_session

logger = logging.getLogger(__name__)


def start_update_flow(sender: str, ref_no: str, user: dict, prefill: dict | None = None):
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
        "current_estimated_completion_date": row.get("estimated_completion_date", ""),
    }

    if prefill and prefill.get("status"):
        # Status pre-filled from LLM
        context["new_status"] = prefill["status"]
        context["new_update"] = prefill.get("latest_update", "")
        if prefill["status"] == "Closed" or prefill.get("estimated_completion_date"):
            context["new_estimated_completion_date"] = prefill.get("estimated_completion_date")
            set_session(sender, "update_confirm", context=context)
            _show_update_preview(sender, row, context, user)
            return
        else:
            set_session(sender, "update_expected_date", context=context)
            send_text(
                sender,
                f"📅 *Expected Completion Date* for *{ref_no}*:\n\n"
                f"When is this task expected to be completed?\n"
                f"(e.g., *10th September*, *by Friday*, *next Monday*, *15 Sep 2026*, or type *skip* to keep current)"
            )
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

    if state == "update_ref_no_input":
        import re
        ref_match = re.search(r'(GEBB[12]|GETT|Common)[-\s]?(\d{1,3})', text.strip(), re.IGNORECASE)
        if ref_match:
            bldg = ref_match.group(1).upper()
            num = int(ref_match.group(2))
            ref_no = f"{bldg}-{num:03d}"
            start_update_flow(sender, ref_no, user)
        else:
            send_text(sender, "Could not find a valid Ref No (e.g. GEBB1-001). Please try again or type *menu*.")

    elif state == "update_status":
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

        if context.get("new_status") == "Closed":
            set_session(sender, "update_confirm", context=context)
            row = read_row(context.get("ref_no"))
            _show_update_preview(sender, row, context, user)
            return

        set_session(sender, "update_expected_date", context=context)
        ref_no = context.get("ref_no", "this task")
        send_text(
            sender,
            f"📅 *Expected Completion Date* for *{ref_no}*:\n\n"
            f"When is this task expected to be completed?\n"
            f"(e.g., *10th September*, *by Friday*, *next Monday*, *15 Sep 2026*, or type *skip* to keep current)"
        )

    elif state == "update_expected_date":
        from facilities.config import parse_facilities_date
        clean = text.strip().lower()
        if clean in ("skip", "no", "none", "na", "-", "—", "cancel", "keep", "current"):
            context["new_estimated_completion_date"] = None
        else:
            parsed_date = parse_facilities_date(text)
            if parsed_date:
                context["new_estimated_completion_date"] = parsed_date
            else:
                send_text(
                    sender,
                    "I couldn't understand that date. Please enter a valid date "
                    "(e.g., *10th September*, *by Friday*, *next Monday*, *15 Sep 2026*) "
                    "or type *skip* to keep current."
                )
                return

        set_session(sender, "update_confirm", context=context)
        row = read_row(context.get("ref_no"))
        _show_update_preview(sender, row, context, user)

    elif state == "update_confirm":
        send_text(sender, "Please use the buttons to *Confirm* or *Cancel* the update.")


def _show_update_preview(sender: str, row: dict | None, context: dict, user: dict):
    """Show before → after preview before committing."""
    ref_no = context.get("ref_no", "—")
    old_status = context.get("current_status", "—")
    new_status = context.get("new_status", "—")
    update_text = context.get("new_update", "")
    new_est = context.get("new_estimated_completion_date")

    old_rag = RAG_STATUS_MAP.get(old_status, {"emoji": "⚪"})
    new_rag = RAG_STATUS_MAP.get(new_status, {"emoji": "⚪"})

    msg = (
        f"🔄 *Update Preview — {ref_no}*\n"
        f"{'─' * 25}\n\n"
        f"*Status:* {old_rag['emoji']} {old_status} → {new_rag['emoji']} {new_status}\n"
    )

    if update_text:
        msg += f"*Note:* {update_text}\n"

    if new_est:
        msg += f"*Estimated Completion Date:* {new_est}\n"
    elif row and row.get("estimated_completion_date"):
        msg += f"*Estimated Completion Date:* {row.get('estimated_completion_date')}\n"

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
    new_est = context.get("new_estimated_completion_date")

    if not ref_no or not new_status:
        send_text(sender, "Missing data. Please start over.")
        clear_session(sender)
        return

    actor = str(user.get("name") or "GEI_BOT")
    results = []

    # Write status
    status_result = write_field(ref_no, "status", new_status, source="gei_bot", actor=actor)
    results.append(("Status", status_result))

    # Write note if provided
    if update_text:
        note_result = write_field(ref_no, "latest_update", update_text, source="gei_bot", actor=actor)
        results.append(("Note", note_result))

    # Write Estimated Completion Date if provided (never touch Actual Completion Date)
    if new_est:
        est_result = write_field(ref_no, "estimated_completion_date", new_est, source="gei_bot", actor=actor)
        results.append(("Estimated Completion Date", est_result))

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
    if new_est:
        msg += f"*Estimated Completion Date:* {new_est}\n"

    msg += f"\n{bot_line}\n{sheet_line}"

    send_text(sender, msg)

    # ── Notify Kanav if this task was created by him ──
    try:
        from notifications.kanav_notifier import is_facilities_task_created_by_kanav, notify_kanav_task_change
        task_row = read_row(ref_no)
        if task_row and is_facilities_task_created_by_kanav(task_row):
            task_title = task_row.get("issue_action", ref_no)
            current_st = context.get("current_status", "Open")
            changes = []
            if new_status == "Closed":
                changes.append(f"Status changed from {current_st} to Closed (Task closed)")
            elif new_status != current_st:
                changes.append(f"Status changed from {current_st} to {new_status}")
            if update_text:
                changes.append(f"Note: {update_text}")
            if new_est:
                changes.append(f"Est. completion: {new_est}")

            change_made = " | ".join(changes) if changes else "Task updated"
            actor_name = user.get("name", actor or "Team Member")
            notify_kanav_task_change(
                task_id=ref_no,
                task_title=task_title,
                change_made=change_made,
                changed_by=actor_name,
                domain="Facilities"
            )
    except Exception as e:
        logger.error(f"Failed to trigger Kanav notification in confirm_update: {e}")

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
