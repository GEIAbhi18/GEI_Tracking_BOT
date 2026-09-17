"""
Screen 04 — Task Card + Actions
=================================
Full task card with all 9 visible fields + Sheet Sync indicator.
Action row: Update / Reassign / Attach / History (4 options → List Message).

Also handles:
  - Reassign flow (Screen 04 action)
  - Attach flow (Screen 04 action)
"""

import logging
import uuid
from datetime import datetime, timezone

from whatsapp.ux import send_text, send_list_message, send_interactive_buttons
from postgrest.types import CountMethod
from db import supabase
from facilities.sheets_client import read_row, write_field, normalize_added_by
from facilities.config import RAG_STATUS_MAP
from facilities.auth import assert_building_access, get_facilities_team_members

logger = logging.getLogger(__name__)


def show_task_card(sender: str, ref_no: str, user: dict):
    """Show the full task card for a Ref No (Screen 04)."""
    row = read_row(ref_no)

    if not row:
        send_text(sender, f"Task *{ref_no}* not found.")
        return

    # Check building access
    building = row.get("building", "")
    try:
        assert_building_access(user, building)
    except PermissionError as e:
        send_text(sender, f"🚫 {str(e)}")
        return

    # Determine sync status
    sync_indicator = _get_sync_indicator(ref_no)

    # Enrich with responsible user
    from facilities.task_filter import enrich_task_with_responsible
    enrich_task_with_responsible(row)
    owner = row.get('owner', 'Unassigned')
    responsible = row.get('responsible_user')
    owner_display = owner
    if responsible and responsible.lower() != owner.lower():
        owner_display = f"{owner} (Responsible: {responsible})"

    # Build the card
    status = row.get("status", "Open")
    rag = RAG_STATUS_MAP.get(status, {"emoji": "⚪", "label": status})

    # Check for attachments
    attach_count = _get_attachment_count(ref_no)
    attach_line = f"📎 *Attachments:* {attach_count} file(s)" if attach_count > 0 else ""

    card = (
        f"📋 *Task Card — {ref_no}*\n"
        f"{'─' * 25}\n\n"
        f"🏗️ *Building:* {building}\n"
        f"📁 *Type:* {row.get('type', '—')}\n"
        f"🔧 *Issue/Action:* {row.get('issue_action', '—')}\n"
        f"👤 *Owner:* {owner_display}\n"
        f"📅 *Planned Date:* {row.get('planned_date') or row.get('target_date', '—') or '—'}\n"
        f"⏳ *Estimated Completion Date:* {row.get('estimated_completion_date', '—') or '—'}\n"
        + (f"✅ *Actual Completion Date:* {row.get('actual_completion_date')}\n" if row.get('actual_completion_date') else "")
        + f"{rag['emoji']} *Status:* {rag['label']}\n"
        f"📝 *Latest Update:* {row.get('latest_update', '—')}\n"
        f"📅 *Date Raised:* {row.get('created_date', '—')}\n"
        f"👤 *Added by:* {normalize_added_by(row.get('added_by') or row.get('last_modified_by_at', '—'))}\n"
    )

    if attach_line:
        card += f"\n{attach_line}\n"

    card += f"\n{sync_indicator}"

    # Send the card first
    send_text(sender, card)

    # Then send the action List Message (4 options → List Message)
    action_rows = [
        {"id": f"fac_update_{ref_no}", "title": "🔄 Update", "description": "Change status or add notes"},
        {"id": f"fac_reassign_{ref_no}", "title": "👤 Reassign", "description": "Assign to another person"},
        {"id": f"fac_attach_{ref_no}", "title": "📎 Attach", "description": "Add photo or document"},
        {"id": f"fac_history_{ref_no}", "title": "📜 History", "description": "View full audit trail"},
    ]

    sections = [{"title": "Task Actions", "rows": action_rows}]
    send_list_message(sender, f"What would you like to do with *{ref_no}*?", "Actions", sections)


def _get_sync_indicator(ref_no: str) -> str:
    """Get the sync status indicator for a task."""
    try:
        # Check for pending syncs
        pending = supabase.table("sync_queue").select("id", count=CountMethod.exact).eq(
            "ref_no", ref_no
        ).eq("status", "pending").execute()

        if pending.count and pending.count > 0:
            return "🔄 *Sheet Sync:* ⏳ Pending"

        # Check for failed syncs
        failed = supabase.table("sync_queue").select("id", count=CountMethod.exact).eq(
            "ref_no", ref_no
        ).eq("status", "failed").execute()

        if failed.count and failed.count > 0:
            return "🔄 *Sheet Sync:* ❌ Failed — auto-retrying"

        return "🔄 *Sheet Sync:* ✅ Synced"

    except Exception:
        return "🔄 *Sheet Sync:* ❓ Unknown"


def _get_attachment_count(ref_no: str) -> int:
    """Count attachments for a task."""
    try:
        res = supabase.table("facilities_attachments").select(
            "id", count=CountMethod.exact
        ).eq("ref_no", ref_no).execute()
        return res.count or 0
    except Exception:
        return 0


# ── Reassign Flow ────────────────────────────────────────────────────────────

def start_reassign_flow(sender: str, ref_no: str, user: dict):
    """Start the reassign flow: show a List Message of valid team members."""
    row = read_row(ref_no)
    if not row:
        send_text(sender, f"Task *{ref_no}* not found.")
        return

    building = row.get("building", "")
    try:
        assert_building_access(user, building)
    except PermissionError as e:
        send_text(sender, f"🚫 {str(e)}")
        return

    # Get team members for this building
    team = get_facilities_team_members(building)

    if not team:
        send_text(sender, f"No team members found for {building}.")
        return

    # Store context
    from facilities.flows.router import set_session
    set_session(sender, "reassign_awaiting", context={"ref_no": ref_no, "building": building})

    rows = []
    for member in team[:10]:  # Max 10 for List Message
        member_name = member.get("name", "Unknown")
        row_title = member_name
        if len(row_title) > 24:
            row_title = row_title[:24]
        rows.append({
            "id": f"fac_assignto_{member_name}",
            "title": row_title,
            "description": member.get("role", "Team Member"),
        })

    sections = [{"title": "Select New Owner", "rows": rows}]
    send_list_message(
        sender,
        f"👤 *Reassign {ref_no}*\n\n"
        f"Current owner: *{row.get('owner', 'Unassigned')}*\n\n"
        f"Select the new owner:",
        "Select Owner",
        sections,
    )


def handle_reassign_selection(sender: str, new_owner: str, user: dict):
    """Handle owner selection from the reassign List Message."""
    from facilities.flows.router import get_session, clear_session

    session = get_session(sender)
    if not session:
        send_text(sender, "Session expired. Please try again.")
        return

    ref_no = session.get("context_json", {}).get("ref_no")
    if not ref_no:
        send_text(sender, "Could not determine which task to reassign.")
        clear_session(sender)
        return

    actor = str(user.get("name") or "GEI_BOT")

    # Write the new owner via the sync pipeline
    result = write_field(ref_no, "owner", new_owner, source="gei_bot", actor=actor)

    if result["status"] == "synced":
        # Log as explicit "Reassigned" action
        from facilities.sheets_client import _log_audit
        _log_audit(ref_no, "gei_bot", actor,
                   f"Reassigned to {new_owner}", "owner",
                   session.get("context_json", {}).get("old_owner"), new_owner)

        msg = (
            f"✅ *Task Reassigned*\n\n"
            f"*{ref_no}* has been reassigned to *{new_owner}*.\n\n"
            f"*GEI_BOT:* ✅ Updated\n"
            f"*Google Sheets:* ✅ Synced"
        )

        # Notify the new owner
        _notify_new_owner(ref_no, new_owner, actor)

    elif result["status"] == "failed":
        msg = (
            f"⚠️ *Task Reassigned (Partial)*\n\n"
            f"*{ref_no}* has been reassigned to *{new_owner}*.\n\n"
            f"*GEI_BOT:* ✅ Updated\n"
            f"*Google Sheets:* ⏳ Sync Pending — auto-retrying"
        )

    elif result["status"] == "conflict":
        msg = f"⚠️ A conflict was detected. Please resolve it first."
    else:
        msg = f"Something went wrong. Please try again."

    send_text(sender, msg)

    # ── Notify Kanav if this task was created by him ──
    try:
        from notifications.kanav_notifier import is_facilities_task_created_by_kanav, notify_kanav_task_change
        task_row = read_row(ref_no)
        if task_row and is_facilities_task_created_by_kanav(task_row):
            old_owner = session.get("context_json", {}).get("old_owner") or task_row.get("owner", "—")
            reassign_str = f"Reassigned to {new_owner}" if (not old_owner or old_owner == "—") else f"Reassigned from {old_owner} to {new_owner}"
            notify_kanav_task_change(
                task_id=ref_no,
                task_title=task_row.get("issue_action", ref_no),
                change_made=reassign_str,
                changed_by=user.get("name", "Team Member"),
                domain="Facilities"
            )
    except Exception as e:
        logger.error(f"Failed to trigger Kanav notification in handle_reassign_selection: {e}")

    clear_session(sender)


def handle_reassign_text(sender: str, text: str, user: dict, session: dict):
    """Handle free-text input during reassign flow."""
    # Treat the text as a name and try to match to a team member
    from facilities.auth import get_facilities_team_members
    ref_no = session.get("context_json", {}).get("ref_no")
    building = session.get("context_json", {}).get("building")

    team = get_facilities_team_members(building)
    from rapidfuzz import fuzz, process as fuzz_process

    names = [m.get("name", "") for m in team]
    match = fuzz_process.extractOne(text.strip(), names, scorer=fuzz.WRatio)

    if match and match[1] >= 70:
        handle_reassign_selection(sender, match[0], user)
    else:
        send_text(sender, f"I couldn't find a team member named \"{text}\". Please select from the list.")


def _notify_new_owner(ref_no: str, new_owner: str, reassigned_by: str):
    """Notify the newly assigned owner via WhatsApp."""
    try:
        from facilities.owner_resolver import get_responsible_user_whatsapp
        recipient = get_responsible_user_whatsapp(new_owner)
        wa = None
        target_name = new_owner
        if recipient:
            wa = recipient["whatsapp_number"]
            target_name = recipient["user_name"]
        else:
            user_res = supabase.table("users").select("whatsapp_number, name").eq("name", new_owner).execute()
            if user_res.data and user_res.data[0].get("whatsapp_number"):
                wa = user_res.data[0]["whatsapp_number"]
                target_name = user_res.data[0]["name"]

        if not wa:
            return

        msg = (
            f"📋 *Task Assigned to You*\n\n"
            f"*{ref_no}* has been assigned to you by *{reassigned_by}*.\n\n"
            f"Type the ref number to view details."
        )
        send_text(wa, msg)
        logger.info(f"Notified {target_name} ({wa}) about reassignment of {ref_no}")

    except Exception as e:
        logger.error(f"Failed to notify new owner {new_owner}: {e}")


# ── Attach Flow ──────────────────────────────────────────────────────────────

def prompt_attachment(sender: str, ref_no: str, user: dict):
    """Prompt the user to send an image or PDF."""
    from facilities.flows.router import set_session
    set_session(sender, "attach_awaiting", context={"ref_no": ref_no})

    send_text(
        sender,
        f"📎 *Attach File — {ref_no}*\n\n"
        f"Send an image or PDF in this chat.\n"
        f"It will be linked to task *{ref_no}*.\n\n"
        f"_Type *cancel* to go back._"
    )


def handle_attachment_upload(sender: str, ref_no: str, image_data: dict, user: dict):
    """Handle an uploaded image/PDF attachment."""
    from facilities.flows.router import clear_session

    try:
        # Download the media from WhatsApp
        media_id = image_data.get("id")
        mime_type = image_data.get("mime_type", "image/jpeg")

        if not media_id:
            send_text(sender, "Could not process the attachment. Please try again.")
            return

        # For now, store a reference — actual Supabase Storage upload
        # requires downloading from Meta CDN first
        file_ext = "jpg" if "image" in mime_type else "pdf"
        file_name = f"{ref_no}_{uuid.uuid4().hex[:6]}.{file_ext}"
        file_url = f"whatsapp_media://{media_id}"  # Placeholder until storage upload

        actor = str(user.get("name") or "GEI_BOT")

        # Store in attachments table
        supabase.table("facilities_attachments").insert({
            "ref_no": ref_no,
            "file_url": file_url,
            "file_name": file_name,
            "file_type": mime_type,
            "uploaded_by": actor,
        }).execute()

        # Write a note to the Latest Update field on the Sheet
        note = f"Photo attached by {actor}"
        write_field(ref_no, "latest_update", note, source="gei_bot", actor=actor)

        send_text(
            sender,
            f"📎 *Attachment Saved*\n\n"
            f"File linked to *{ref_no}* successfully.\n\n"
            f"*GEI_BOT:* ✅ Stored\n"
            f"*Google Sheets:* Note added to Latest Update"
        )

        clear_session(sender)

    except Exception as e:
        logger.error(f"Attachment upload failed for {ref_no}: {e}")
        send_text(sender, "Failed to save attachment. Please try again.")
        clear_session(sender)
