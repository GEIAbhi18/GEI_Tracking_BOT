"""
Screen 15 — Status Validation
================================
Reject invalid statuses → show valid options as List Message.
Reopening Closed tasks → explicit confirm with Reply Buttons.
"""

import logging

from whatsapp.ux import send_text, send_list_message, send_interactive_buttons
from facilities.config import VALID_STATUSES, RAG_STATUS_MAP
from facilities.sheets_client import write_field
from facilities.flows.router import get_session, set_session, clear_session

logger = logging.getLogger(__name__)


def show_invalid_status(sender: str, attempted_status: str, user: dict):
    """Show the valid statuses when an invalid one is provided."""
    rows = []
    for status in VALID_STATUSES:
        rag = RAG_STATUS_MAP.get(status, {"emoji": "⚪"})
        row_title = f"{rag['emoji']} {status}"
        if len(row_title) > 24:
            row_title = row_title[:24]
        rows.append({"id": f"fac_status_{status}", "title": row_title})

    sections = [{"title": "Valid Statuses", "rows": rows}]
    send_list_message(
        sender,
        f"⚠️ *\"{attempted_status}\"* is not a valid status.\n\n"
        f"Please select from the valid options:",
        "Select Status",
        sections,
    )


def prompt_reopen_confirm(sender: str, ref_no: str, user: dict):
    """Require explicit confirmation to reopen a Closed task."""
    buttons = [
        {"id": "fac_reopen_confirm", "title": "🔄 Reopen Task"},
        {"id": "fac_reopen_cancel", "title": "❌ Cancel"},
    ]
    send_interactive_buttons(
        sender,
        f"⚠️ *Reopen Task — {ref_no}*\n\n"
        f"This task is currently *Closed*.\n\n"
        f"Reopening it will change the status back to *Open* "
        f"and will be logged as a *re-escalation event*.\n\n"
        f"Are you sure?",
        buttons,
    )


def confirm_reopen(sender: str, user: dict):
    """Confirm reopening a Closed task."""
    session = get_session(sender)
    if not session:
        send_text(sender, "Session expired.")
        return

    context = session.get("context_json", {})
    ref_no = context.get("ref_no")

    if not ref_no:
        send_text(sender, "Could not determine which task to reopen.")
        clear_session(sender)
        return

    actor = str(user.get("name") or "GEI_BOT")

    # Write the status change
    result = write_field(ref_no, "status", "Open", source="gei_bot", actor=actor)

    # Log as a re-escalation event
    from facilities.sheets_client import _log_audit
    _log_audit(ref_no, "gei_bot", actor,
               "Task reopened (re-escalation)", "status", "Closed", "Open")

    if result["status"] == "synced":
        sheet_line = "✅ *Google Sheets:* Synced"
    else:
        sheet_line = "⏳ *Google Sheets:* Sync Pending"

    msg = (
        f"🔄 *Task Reopened — {ref_no}*\n\n"
        f"*Status:* 🟢 Closed → 🔴 Open\n"
        f"*Event:* Re-escalation\n\n"
        f"✅ *GEI_BOT:* Updated\n"
        f"{sheet_line}"
    )

    send_text(sender, msg)

    # ── Notify Kanav if this task was created by him ──
    try:
        from facilities.sheets_client import read_row
        from notifications.kanav_notifier import is_facilities_task_created_by_kanav, notify_kanav_task_change
        task_row = read_row(ref_no)
        if task_row and is_facilities_task_created_by_kanav(task_row):
            notify_kanav_task_change(
                task_id=ref_no,
                task_title=task_row.get("issue_action", ref_no),
                change_made="Status changed from Closed to Open (Reopened)",
                changed_by=actor or "Team Member",
                domain="Facilities"
            )
    except Exception as e:
        logger.error(f"Reopen Kanav notification failed: {e}")

    clear_session(sender)


def cancel_reopen(sender: str, user: dict):
    """Cancel the reopen."""
    clear_session(sender)
    send_text(sender, "Reopen cancelled. The task remains *Closed*.\n\n_Type *menu* to go back._")
