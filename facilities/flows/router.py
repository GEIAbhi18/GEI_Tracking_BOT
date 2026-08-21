from __future__ import annotations

"""
Facilities Module — Flow Router
==================================
Central dispatcher for all Facilities conversational flows.

Routing logic:
  1. Check if user has an active facilities_session with a flow state
     → Route to the in-progress flow handler
  2. Check if the message is an interactive button/list reply
     → Route by button/list ID prefix
  3. For free text: extract intent via LLM
     → Route to the appropriate flow handler
  4. Fallback: show the Facilities home menu
"""

import logging
import json
from datetime import datetime, timezone

from db import supabase
from facilities.auth import resolve_facilities_user

logger = logging.getLogger(__name__)


# ── Session Management ───────────────────────────────────────────────────────

def get_session(whatsapp_number: str) -> dict | None:
    """Get the current Facilities session for a user."""
    try:
        res = supabase.table("facilities_sessions").select("*").eq(
            "whatsapp_number", whatsapp_number
        ).execute()
        if res.data:
            session = res.data[0]
            # Parse JSON fields
            if isinstance(session.get("draft_task_json"), str):
                try:
                    session["draft_task_json"] = json.loads(session["draft_task_json"])
                except Exception:
                    session["draft_task_json"] = {}
            if isinstance(session.get("context_json"), str):
                try:
                    session["context_json"] = json.loads(session["context_json"])
                except Exception:
                    session["context_json"] = {}
            return session
        return None
    except Exception as e:
        logger.error(f"get_session failed for {whatsapp_number}: {e}")
        return None


def set_session(whatsapp_number: str, flow_state: str,
                draft: dict = None, context: dict = None):
    """Create or update a Facilities session."""
    try:
        payload = {
            "whatsapp_number": whatsapp_number,
            "current_flow_state": flow_state,
            "last_active_at": datetime.now(timezone.utc).isoformat(),
        }
        if draft is not None:
            payload["draft_task_json"] = json.dumps(draft)
        if context is not None:
            payload["context_json"] = json.dumps(context)

        supabase.table("facilities_sessions").upsert(
            payload, on_conflict="whatsapp_number"
        ).execute()
    except Exception as e:
        logger.error(f"set_session failed for {whatsapp_number}: {e}")


def clear_session(whatsapp_number: str):
    """Clear/delete the Facilities session for a user."""
    try:
        supabase.table("facilities_sessions").delete().eq(
            "whatsapp_number", whatsapp_number
        ).execute()
    except Exception as e:
        logger.error(f"clear_session failed for {whatsapp_number}: {e}")


# ── Main Router ──────────────────────────────────────────────────────────────

def route_facilities_message(sender: str, text: str = None,
                               button_id: str = None, user: dict = None,
                               image_data: dict = None,
                               voice_transcript: str = None):
    """
    Main entry point for all Facilities module messages.

    Args:
        sender: WhatsApp number
        text: Plain text message (if any)
        button_id: Interactive button/list reply ID (if any)
        user: Authenticated user dict
        image_data: Image attachment data (if any)
        voice_transcript: Transcribed voice note text (if any)
    """
    # Resolve Facilities user
    if not user:
        user = resolve_facilities_user(sender)

    if not user or not user.get("is_facilities_user"):
        # Not a Facilities user — shouldn't reach here, but handle gracefully
        from whatsapp.ux import send_text
        send_text(sender, "You are not registered as a Facilities team member. Please contact your administrator.")
        return

    # Update session timestamp
    session = get_session(sender)

    # 1. Handle interactive button/list replies
    if button_id:
        _route_button(sender, button_id, user, session)
        return

    # 2. Handle image attachments
    if image_data:
        _route_image(sender, image_data, user, session)
        return

    # 3. Handle voice transcriptions
    if voice_transcript:
        _route_voice(sender, voice_transcript, user, session)
        return

    # 4. Handle text messages
    if text:
        _route_text(sender, text, user, session)
        return


def _route_button(sender: str, button_id: str, user: dict, session: dict):
    """Route interactive button/list reply IDs."""
    logger.info(f"Facilities button route: {button_id}")

    # ── Home Menu Actions ────────────────────────────────────────────────
    if button_id == "fac_my_tasks":
        from facilities.flows.my_tasks import show_my_tasks
        show_my_tasks(sender, user)

    elif button_id == "fac_team_tasks":
        from facilities.flows.building_filter import prompt_building_filter
        prompt_building_filter(sender, user, next_action="team_tasks")

    elif button_id == "fac_completed_tasks":
        from facilities.flows.completed_tasks import prompt_completed_tasks_building
        prompt_completed_tasks_building(sender, user)

    elif button_id == "fac_create_task":
        from facilities.flows.create_task import start_create_flow
        start_create_flow(sender, user)

    elif button_id == "fac_summary":
        from facilities.flows.summary import show_summary
        show_summary(sender, user)

    elif button_id == "fac_sync_status":
        from facilities.flows.sync_status import show_sync_status
        show_sync_status(sender, user)

    # ── Building Filter Selection ────────────────────────────────────────
    elif button_id.startswith("fac_bldg_"):
        building = button_id.replace("fac_bldg_", "")
        _handle_building_selection(sender, building, user, session)

    # ── Task Card Actions ────────────────────────────────────────────────
    elif button_id.startswith("fac_view_"):
        ref_no = button_id.replace("fac_view_", "")
        from facilities.flows.task_card import show_task_card
        show_task_card(sender, ref_no, user)

    elif button_id.startswith("fac_update_"):
        ref_no = button_id.replace("fac_update_", "")
        from facilities.flows.update_task import start_update_flow
        start_update_flow(sender, ref_no, user)

    elif button_id.startswith("fac_reassign_"):
        ref_no = button_id.replace("fac_reassign_", "")
        from facilities.flows.task_card import start_reassign_flow
        start_reassign_flow(sender, ref_no, user)

    elif button_id.startswith("fac_attach_"):
        ref_no = button_id.replace("fac_attach_", "")
        from facilities.flows.task_card import prompt_attachment
        prompt_attachment(sender, ref_no, user)

    elif button_id.startswith("fac_history_"):
        ref_no = button_id.replace("fac_history_", "")
        from facilities.flows.history import show_history
        show_history(sender, ref_no, user)

    # ── Task Creation Flow ───────────────────────────────────────────────
    elif button_id.startswith("fac_type_"):
        task_type = button_id.replace("fac_type_", "")
        from facilities.flows.create_task import handle_type_selection
        handle_type_selection(sender, task_type, user)

    elif button_id == "fac_confirm_create":
        from facilities.flows.create_task import confirm_create
        confirm_create(sender, user)

    elif button_id == "fac_edit_draft":
        from facilities.flows.create_task import edit_draft
        edit_draft(sender, user)

    elif button_id == "fac_cancel_create":
        from facilities.flows.create_task import cancel_create
        cancel_create(sender, user)

    # ── Duplicate Detection ──────────────────────────────────────────────
    elif button_id.startswith("fac_update_existing_"):
        ref_no = button_id.replace("fac_update_existing_", "")
        from facilities.flows.update_task import start_update_flow
        start_update_flow(sender, ref_no, user)

    elif button_id == "fac_create_anyway":
        from facilities.flows.create_task import confirm_create
        confirm_create(sender, user, skip_duplicate_check=True)

    # ── Status Validation ────────────────────────────────────────────────
    elif button_id == "fac_confirm_update":
        from facilities.flows.update_task import confirm_update
        confirm_update(sender, user)

    elif button_id == "fac_cancel_update":
        clear_session(sender)
        from whatsapp.ux import send_text as _st
        _st(sender, "❌ Update cancelled.\n\n_Type *menu* to go back._")

    elif button_id.startswith("fac_status_"):
        new_status = button_id.replace("fac_status_", "")
        from facilities.flows.update_task import handle_status_selection
        handle_status_selection(sender, new_status, user)

    elif button_id == "fac_reopen_confirm":
        from facilities.flows.status_validation import confirm_reopen
        confirm_reopen(sender, user)

    elif button_id == "fac_reopen_cancel":
        from facilities.flows.status_validation import cancel_reopen
        cancel_reopen(sender, user)

    # ── Conflict Resolution ──────────────────────────────────────────────
    elif button_id.startswith("fac_keep_sheet_"):
        conflict_id = button_id.replace("fac_keep_sheet_", "")
        from facilities.flows.conflict_ui import resolve_keep_sheet
        resolve_keep_sheet(sender, conflict_id, user)

    elif button_id.startswith("fac_keep_bot_"):
        conflict_id = button_id.replace("fac_keep_bot_", "")
        from facilities.flows.conflict_ui import resolve_keep_bot
        resolve_keep_bot(sender, conflict_id, user)

    elif button_id.startswith("fac_conflict_history_"):
        ref_no = button_id.replace("fac_conflict_history_", "")
        from facilities.flows.history import show_history
        show_history(sender, ref_no, user)

    # ── Reassign Flow ────────────────────────────────────────────────────
    elif button_id.startswith("fac_assignto_"):
        new_owner = button_id.replace("fac_assignto_", "")
        from facilities.flows.task_card import handle_reassign_selection
        handle_reassign_selection(sender, new_owner, user)

    # ── Voice Confirmation ───────────────────────────────────────────────
    elif button_id == "fac_voice_confirm_all":
        from facilities.flows.voice_handler import confirm_all_voice_ops
        confirm_all_voice_ops(sender, user)

    elif button_id == "fac_voice_cancel":
        from facilities.flows.voice_handler import cancel_voice_ops
        cancel_voice_ops(sender, user)

    # ── Back to Home ─────────────────────────────────────────────────────
    elif button_id == "fac_home":
        from facilities.flows.home import show_home
        show_home(sender, user)

    # ── View All Tasks (pagination) ──────────────────────────────────────
    elif button_id.startswith("fac_viewall_"):
        parts = button_id.replace("fac_viewall_", "").split("_", 1)
        if len(parts) == 2:
            building, task_type = parts
            from facilities.flows.my_tasks import show_tasks_by_type
            show_tasks_by_type(sender, user, building, task_type)

    # ── Daily Digest ─────────────────────────────────────────────────────
    elif button_id == "fac_daily_digest":
        from facilities.flows.daily_digest import show_daily_digest
        show_daily_digest(sender, user)

    # ── Completed Tasks ──────────────────────────────────────────────────
    elif button_id.startswith("fac_completed_bldg_"):
        bldg = button_id.replace("fac_completed_bldg_", "")
        from facilities.flows.completed_tasks import show_completed_tasks
        show_completed_tasks(sender, user, bldg)

    else:
        logger.warning(f"Unknown Facilities button ID: {button_id}")
        from whatsapp.ux import send_text
        send_text(sender, "Sorry, I didn't understand that action. Let me show you the menu.")
        from facilities.flows.home import show_home
        show_home(sender, user)


def _route_text(sender: str, text: str, user: dict, session: dict):
    """Route free-text messages."""
    # Check for greeting/menu triggers
    clean = text.strip().lower()
    if clean in ("hi", "hello", "hey", "menu", "start", "home"):
        clear_session(sender)
        from facilities.flows.home import show_home
        show_home(sender, user)
        return

    # Check for completed tasks triggers
    if any(k in clean for k in ("completed task", "completed tasks", "closed task", "closed tasks", "show completed", "show closed")):
        from facilities.auth import fuzzy_match_building
        matched_bldg = fuzzy_match_building(text)
        if matched_bldg:
            from facilities.flows.completed_tasks import show_completed_tasks
            show_completed_tasks(sender, user, matched_bldg)
        elif "all" in clean:
            from facilities.flows.completed_tasks import show_completed_tasks
            show_completed_tasks(sender, user, "all")
        else:
            from facilities.flows.completed_tasks import prompt_completed_tasks_building
            prompt_completed_tasks_building(sender, user)
        return

    # Check if user is in a multi-step flow
    if session and session.get("current_flow_state"):
        _route_in_flow_text(sender, text, user, session)
        return

    # Extract intent via LLM
    from facilities.llm import extract_intent
    result = extract_intent(text)

    if not result.get("intents"):
        from facilities.flows.home import show_home
        show_home(sender, user)
        return

    primary = result["intents"][0]
    intent = primary.get("intent")
    entities = primary.get("entities", {})
    confidence = primary.get("confidence", 0)

    logger.info(f"Facilities intent: {intent} (confidence: {confidence}) for {sender}")

    if intent == "greeting":
        from facilities.flows.home import show_home
        show_home(sender, user)

    elif intent == "view_my_tasks":
        from facilities.flows.my_tasks import show_my_tasks
        show_my_tasks(sender, user)

    elif intent == "view_team_tasks":
        building = entities.get("building")
        if building:
            from facilities.flows.team_tasks import show_team_tasks
            show_team_tasks(sender, building, user)
        else:
            from facilities.flows.building_filter import prompt_building_filter
            prompt_building_filter(sender, user, next_action="team_tasks")

    elif intent == "create_task":
        from facilities.flows.create_task import start_create_flow
        start_create_flow(sender, user, prefill=entities)

    elif intent == "update_task":
        ref_no = entities.get("ref_no")
        if ref_no:
            from facilities.flows.update_task import start_update_flow
            start_update_flow(sender, ref_no, user, prefill=entities)
        else:
            from facilities.flows.update_task import prompt_ref_no_for_update
            prompt_ref_no_for_update(sender, user)

    elif intent == "view_task_detail":
        ref_no = entities.get("ref_no")
        if ref_no:
            from facilities.flows.task_card import show_task_card
            show_task_card(sender, ref_no, user)
        else:
            from whatsapp.ux import send_text
            send_text(sender, "Please provide the task Ref No (e.g., GEBB1-001).")

    elif intent == "view_summary":
        from facilities.flows.summary import show_summary
        show_summary(sender, user)

    elif intent == "view_sync_status":
        from facilities.flows.sync_status import show_sync_status
        show_sync_status(sender, user)

    elif intent == "view_history":
        ref_no = entities.get("ref_no")
        if ref_no:
            from facilities.flows.history import show_history
            show_history(sender, ref_no, user)
        else:
            from whatsapp.ux import send_text
            send_text(sender, "Please provide the task Ref No to view history (e.g., GEBB1-001).")

    elif intent == "daily_digest":
        from facilities.flows.daily_digest import show_daily_digest
        show_daily_digest(sender, user)

    elif intent == "help":
        _show_help(sender)

    else:
        from facilities.flows.home import show_home
        show_home(sender, user)


def _route_in_flow_text(sender: str, text: str, user: dict, session: dict):
    """Route text when user is in a multi-step flow."""
    state = session.get("current_flow_state", "")

    # Create task flow states
    if state.startswith("create_"):
        from facilities.flows.create_task import handle_create_flow_text
        handle_create_flow_text(sender, text, user, session)

    # Update task flow states
    elif state.startswith("update_"):
        from facilities.flows.update_task import handle_update_flow_text
        handle_update_flow_text(sender, text, user, session)

    # Building filter
    elif state == "building_filter":
        from facilities.flows.building_filter import handle_building_text
        handle_building_text(sender, text, user, session)

    # Completed tasks building filter
    elif state == "completed_tasks_building":
        from facilities.auth import fuzzy_match_building
        bldg = fuzzy_match_building(text)
        if bldg:
            from facilities.flows.completed_tasks import show_completed_tasks
            show_completed_tasks(sender, user, bldg)
        elif text.strip().lower() in ("all", "all buildings", "every building"):
            from facilities.flows.completed_tasks import show_completed_tasks
            show_completed_tasks(sender, user, "all")
        else:
            from facilities.flows.completed_tasks import prompt_completed_tasks_building
            prompt_completed_tasks_building(sender, user)

    # Reassign flow
    elif state.startswith("reassign_"):
        from facilities.flows.task_card import handle_reassign_text
        handle_reassign_text(sender, text, user, session)

    # Voice confirmation
    elif state == "voice_confirm":
        from facilities.flows.voice_handler import handle_voice_confirm_text
        handle_voice_confirm_text(sender, text, user, session)

    else:
        # Unknown state — clear and show home
        clear_session(sender)
        from facilities.flows.home import show_home
        show_home(sender, user)


def _route_image(sender: str, image_data: dict, user: dict, session: dict):
    """Route image attachments."""
    if session and session.get("current_flow_state", "").startswith("attach_"):
        ref_no = session.get("context_json", {}).get("ref_no")
        if ref_no:
            from facilities.flows.task_card import handle_attachment_upload
            handle_attachment_upload(sender, ref_no, image_data, user)
            return

    from whatsapp.ux import send_text
    send_text(sender, "To attach an image to a task, first open the task card and tap *Attach*.")


def _route_voice(sender: str, transcript: str, user: dict, session: dict):
    """Route voice note transcriptions."""
    from facilities.flows.voice_handler import handle_voice_note
    handle_voice_note(sender, transcript, user)


def _handle_building_selection(sender: str, building: str, user: dict, session: dict):
    """Handle a building selection from the filter."""
    next_action = None
    if session and session.get("context_json"):
        next_action = session["context_json"].get("next_action")

    if next_action == "team_tasks":
        from facilities.flows.team_tasks import show_team_tasks
        show_team_tasks(sender, building, user)
    elif next_action == "create_task":
        from facilities.flows.create_task import handle_building_selection
        handle_building_selection(sender, building, user)
    else:
        from facilities.flows.team_tasks import show_team_tasks
        show_team_tasks(sender, building, user)


def _show_help(sender: str):
    """Send help message."""
    from whatsapp.ux import send_text
    msg = (
        "🔧 *GEI Facilities Bot — Help*\n\n"
        "Here's what I can do:\n\n"
        "📋 *My Tasks* — View your assigned tasks\n"
        "👥 *Team Tasks* — View tasks by building\n"
        "➕ *Create Task* — Create a new facilities task\n"
        "🔄 *Update Task* — Update status or add notes\n"
        "📊 *Summary* — Task counts by building/status\n"
        "🔗 *Sync Status* — Google Sheets sync health\n"
        "📜 *History* — View full audit trail for a task\n"
        "📝 *Daily Digest* — Today's activity summary\n\n"
        "_You can also just tell me what you need in plain language, "
        "or send a voice note!_\n\n"
        "Type *menu* to see the main menu."
    )
    send_text(sender, msg)


# ── Entry Point Check ────────────────────────────────────────────────────────

def is_facilities_user(whatsapp_number: str) -> bool:
    """
    Quick check if a WhatsApp number belongs to a Facilities user.
    Used by the main webhook to decide whether to route to this module.
    """
    user = resolve_facilities_user(whatsapp_number)
    return user is not None and user.get("is_facilities_user", False)
