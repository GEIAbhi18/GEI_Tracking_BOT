"""
WhatsApp Webhook — Production Entry Point
==========================================
Handles:
  - GET  /webhook  → Meta verification handshake
  - POST /webhook  → Incoming messages (text + interactive button replies + voice notes)

Flow routing:
  1. Interactive button replies → task_assignment.handle_button_reply()
  2. Audio messages (voice notes) → audio_handler.handle_voice_note() → core engine
  3. Text messages in WA state  → task_assignment.handle_text_reply()
  4. All other text             → core bot engine (process_user_message)
"""

import os
import sys
import logging
import asyncio

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask, request, jsonify
from core.logic import process_user_message
from core.error_messages import friendly_system_error
from whatsapp.task_assignment import (
    send_text,
    handle_button_reply,
    handle_text_reply,
    _send_document_wa,
)

app = Flask(__name__)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Env vars ─────────────────────────────────────────────────────────────────
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")


# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOK VERIFICATION (GET)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return challenge, 200
    return "Verification failed", 403


# ─────────────────────────────────────────────────────────────────────────────
# INCOMING MESSAGES (POST)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/webhook', methods=['POST'])
def handle_whatsapp_message():
    try:
        body = request.get_json()
        if not body:
            return jsonify({"status": "no data"}), 200

        logger.info(f"Incoming WA payload: {str(body)[:500]}")

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # ── Skip delivery/read status updates ────────────────────────
                if value.get("statuses"):
                    continue

                messages = value.get("messages", [])
                if not messages:
                    continue

                for message in messages:
                    sender = message.get("from", "")
                    msg_type = message.get("type", "")

                    # ── Interactive button reply ──────────────────────────────
                    if msg_type == "interactive":
                        _handle_interactive(sender, message)

                    # ── Voice note (audio) ─────────────────────────────────────
                    elif msg_type == "audio":
                        _handle_audio(sender, message)

                    # ── Plain text ────────────────────────────────────────────
                    elif msg_type == "text":
                        text = message.get("text", {}).get("body", "").strip()
                        if text:
                            _handle_text(sender, text)

                    else:
                        logger.info(f"Unsupported message type '{msg_type}' from {sender}")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"status": "error"}), 200


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL ROUTING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _handle_interactive(sender: str, message: dict):
    """Route interactive button replies to the task assignment module."""
    try:
        interactive = message.get("interactive", {})
        i_type = interactive.get("type")

        if i_type == "button_reply":
            button_id = interactive["button_reply"]["id"]
            logger.info(f"Button reply from {sender}: {button_id}")
            handle_button_reply(sender, button_id)
        else:
            logger.warning(f"Unhandled interactive type '{i_type}' from {sender}")

    except (KeyError, TypeError) as e:
        logger.error(f"Error parsing interactive message from {sender}: {e}")


def _handle_text(sender: str, text: str, voice_note: bool = False):
    """
    Route text messages:
      1. Check for UNDO command (voice note context)
      2. If sender is in a WA task-assignment state → task_assignment module
      3. For voice notes: check if batch update (multiple tasks) → batch handler
      4. Otherwise → core bot engine with a WhatsApp-native send_reply_func

    Args:
        sender: WhatsApp phone number (E.164 without '+')
        text: The message text (typed or transcribed from voice)
        voice_note: True if this text originated from a voice note transcription
    """
    # 0. Check for UNDO command (works from both text and voice)
    if text.strip().upper() == "UNDO" and not voice_note:
        _handle_voice_undo(sender)
        return

    # 1. Task assignment multi-step state (e.g. rejection reason, new date)
    if handle_text_reply(sender, text):
        logger.info(f"Text handled by task_assignment module for {sender}")
        return

    # 2. Voice note batch detection — multiple tasks in one message
    if voice_note:
        try:
            from whatsapp.voice_batch_handler import is_batch_transcript, extract_batch_updates
            if is_batch_transcript(text):
                logger.info(f"Batch voice note detected from {sender}")
                batch_updates = extract_batch_updates(text)
                if batch_updates and len(batch_updates) > 1:
                    _handle_voice_batch(sender, batch_updates)
                    return
                logger.info("Batch extraction returned single/no updates, falling through to normal pipeline")
        except Exception as e:
            logger.warning(f"Batch detection failed, falling through: {e}")

    # 3. Core bot engine — pass a WA-native reply function so documents work
    source_label = "voice" if voice_note else "text"
    logger.info(f"{source_label.capitalize()} from {sender} → core engine: {text[:80]}")

    # Track pre-update state for voice note UNDO capability
    pre_update_snapshot = None
    if voice_note:
        pre_update_snapshot = _capture_pre_update_snapshot(sender, text)

    async def wa_send_reply(text: str = None, document: str = None, target_user_id: int = None):
        """
        WhatsApp-aware send function.
        - text messages → sent as plain text
        - document (PDF path) → uploaded to WA media API, then sent as document
        """
        if text:
            send_text(sender, text)
        if document:
            _send_document_wa(sender, document)

    try:
        asyncio.run(
            process_user_message(user_id=sender, text=text, send_reply_func=wa_send_reply)
        )

        # After successful processing, store voice action for UNDO
        if voice_note and pre_update_snapshot:
            _store_voice_action(sender, pre_update_snapshot)

    except Exception as e:
        logger.error(f"Core engine error for {sender}: {e}", exc_info=True)
        # Send a friendly message so the user isn't left hanging
        try:
            send_text(sender, friendly_system_error(text))
        except Exception:
            pass  # Last resort — can't even send the error message


def _handle_voice_batch(sender: str, updates: list):
    """
    Process multiple task updates from a single voice note.

    For each update:
      - Resolve project + task
      - If ambiguous → collect for later disambiguation
      - If completed → mark complete and queue image request
      - Otherwise → save progress update

    Sends a single combined summary at the end.
    """
    from db import (
        get_projects, get_all_tasks, save_update, complete_task,
        add_blocker as db_add_blocker, get_user_by_telegram_id
    )
    from core.utils import resolve_project, resolve_task_from_list
    from core.conversation_state import set_state

    projects = get_projects()
    all_tasks = get_all_tasks()

    # Resolve sender's DB user
    emp_uuid = None
    try:
        from whatsapp.task_assignment import get_user_by_whatsapp
        user = get_user_by_whatsapp(sender)
        if user:
            emp_uuid = user['id']
    except Exception:
        pass

    if not emp_uuid:
        try:
            u_info = get_user_by_telegram_id(int(sender))
            emp_uuid = u_info['id'] if u_info else None
        except Exception:
            pass

    saved = []        # Successfully saved updates
    completed = []    # Tasks marked complete
    ambiguous = []    # Couldn't resolve — need user input
    failed = []       # Couldn't find task at all

    for upd in updates:
        task_name = upd["task_name"]
        project_name = upd.get("project_name")
        progress = upd.get("progress")
        is_complete = upd.get("completed", False)
        blocker = upd.get("blocker")

        # Resolve project to narrow task search
        active_project_id = None
        if project_name:
            p_match = resolve_project(project_name, projects)
            if p_match:
                active_project_id = p_match['id']

        # Resolve task
        match = resolve_task_from_list(
            task_name, all_tasks, active_project_id=active_project_id
        )

        # Ambiguous? 
        if not match and resolve_task_from_list.ambiguous_matches:
            amb_tasks = resolve_task_from_list.ambiguous_matches
            ambiguous.append({
                "query": task_name,
                "options": amb_tasks,
                "progress": progress,
                "completed": is_complete,
                "blocker": blocker,
            })
            continue

        # Not found?
        if not match:
            failed.append(task_name)
            continue

        # Process the update
        prog_val = progress if progress is not None else (match.get('progress', 0) or 0)
        if is_complete:
            prog_val = 100

        blocker_text = blocker or "None"
        save_update(match['id'], prog_val, blocker_text, [], emp_uuid)

        if blocker and blocker.lower() not in ["none", "null", ""]:
            db_add_blocker(match['id'], blocker)

        if is_complete:
            complete_task(match['id'])
            p_name = ""
            if isinstance(match.get('projects'), dict):
                p_name = match['projects'].get('name', '')
            completed.append({"name": match['name'], "project": p_name, "id": match['id']})
        else:
            saved.append({
                "name": match['name'],
                "progress": prog_val,
                "blocker": blocker,
            })

    # Build summary message
    msg_parts = []

    if saved:
        msg_parts.append("✅ *Updates saved:*")
        for s in saved:
            line = f"  • {s['name']} — {s['progress']}%"
            if s.get('blocker'):
                line += f" 🛑 {s['blocker']}"
            msg_parts.append(line)

    if completed:
        msg_parts.append("\n🎉 *Marked complete:*")
        for c in completed:
            proj = f" ({c['project']})" if c.get('project') else ""
            msg_parts.append(f"  • {c['name']}{proj}")

    if failed:
        msg_parts.append("\n⚠️ *Couldn't find:*")
        for f_name in failed:
            msg_parts.append(f"  • \"{f_name}\" — check the task name")

    if not msg_parts:
        send_text(sender, "Couldn't process any updates from your voice note. Please try again.")
        return

    summary = "\n".join(msg_parts)
    send_text(sender, summary)

    # Handle ambiguous tasks — ask for each one
    if ambiguous:
        # Queue the first ambiguous item for disambiguation
        first = ambiguous[0]
        amb_tasks = first["options"]
        msg = f"\n\nMultiple tasks match *\"{first['query']}\"*. Which one?\n\n"
        for i, t in enumerate(amb_tasks, 1):
            p_name = t.get('projects', {}).get('name', '') if isinstance(t.get('projects'), dict) else ''
            msg += f"{i}. {t['name']}" + (f" ({p_name})" if p_name else "") + "\n"
        msg += "\nReply with the number."

        set_state(sender, {
            "action": "disambiguate_update",
            "step": "waiting_for_choice",
            "task_options": [t['id'] for t in amb_tasks],
            "task_names": [t['name'] for t in amb_tasks],
            "progress_str": str(first.get("progress")) if first.get("progress") is not None else None,
            "deadline": None,
            "images": [],
            # Queue remaining ambiguous items
            "pending_ambiguous": ambiguous[1:] if len(ambiguous) > 1 else [],
        })
        send_text(sender, msg)

    # Ask for proof images if any tasks were completed
    elif completed:
        comp_names = ", ".join([c['name'] for c in completed])
        set_state(sender, {
            "action": "voice_batch_image_confirm",
            "step": "waiting_for_choice",
            "completed_task_ids": [c['id'] for c in completed],
            "completed_task_names": [c['name'] for c in completed],
        })
        send_text(
            sender,
            f"\n📸 *{comp_names}* marked complete.\n"
            f"Do you want to add proof images?\n\n"
            f"1. Yes\n2. No"
        )


# ─────────────────────────────────────────────────────────────────────────────
# VOICE NOTE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def _handle_audio(sender: str, message: dict):
    """
    Handle an incoming voice note (audio message) from WhatsApp.

    Pipeline:
      1. Download & transcribe via audio_handler
      2. On failure → send error-specific friendly reply
      3. On success → send acknowledgement with transcript
      4. Check for UNDO command in transcript
      5. Feed transcript into the SAME _handle_text pipeline as typed messages
    """
    media_id = message.get("audio", {}).get("id")
    if not media_id:
        logger.warning(f"Audio message from {sender} has no media ID")
        send_text(sender, "🎙️ Couldn't process your voice note — no audio found.")
        return

    logger.info(f"Voice note received from {sender}, media_id: {media_id}")

    # Lazy import — avoid loading groq SDK at server startup
    from whatsapp.audio_handler import handle_voice_note

    # Step 1: Download + Transcribe
    result = handle_voice_note(media_id, sender)

    # Step 2: Handle errors with specific friendly messages
    if not result["success"]:
        error_type = result.get("error_type", "unknown")
        logger.warning(f"Voice note failed for {sender}: {error_type} — {result.get('error')}")

        error_messages = {
            "download_failed": (
                "🎙️ Couldn't download your voice note. "
                "WhatsApp sometimes delays audio delivery. "
                "Please resend or type your update."
            ),
            "transcription_failed": (
                "🎙️ Transcription failed right now. "
                "Please type your update — "
                "voice notes will be back shortly."
            ),
            "rate_limit": (
                "🎙️ Transcription failed right now. "
                "Please type your update — "
                "voice notes will be back shortly."
            ),
            "empty_transcript": (
                "🎙️ Couldn't hear anything in your voice note. "
                "Try recording again — speak clearly and close to the mic."
            ),
        }

        reply = error_messages.get(error_type, (
            "🎙️ Sorry, I couldn't process your voice note. "
            "Please try again or type your update instead."
        ))
        send_text(sender, reply)
        return

    transcript = result["transcript"]
    logger.info(f"Voice note transcribed for {sender}: {transcript[:100]}")

    # Step 3: Send immediate acknowledgement BEFORE processing
    send_text(
        sender,
        f"🎙️ Got your voice note. Processing...\n\n"
        f"_I heard:_ \"{transcript}\""
    )

    # Step 4: Check for UNDO command
    if transcript.strip().upper() == "UNDO":
        _handle_voice_undo(sender)
        return

    # Step 5: Store voice action context for potential UNDO
    #         (will be populated AFTER the task update completes)
    #         The _handle_text pipeline handles everything else.

    # Step 6: Feed transcript into the SAME pipeline as typed messages
    _handle_text(sender, transcript, voice_note=True)


def _handle_voice_undo(sender: str):
    """
    Handle UNDO command from a voice note or text.
    Reverts the last voice-note update if within 5 minutes.
    """
    try:
        from whatsapp.task_assignment import get_user_by_whatsapp
        from db import supabase
        from datetime import datetime, timedelta
        import json

        user = get_user_by_whatsapp(sender)
        if not user:
            send_text(sender, "Couldn't identify you — please contact Kanav.")
            return

        # Check wa_task_states for last_voice_action
        try:
            r = supabase.table("wa_task_states").select("last_voice_action").eq(
                "whatsapp_number", sender
            ).execute()
            state_row = r.data[0] if r.data else None
        except Exception:
            state_row = None

        if not state_row or not state_row.get("last_voice_action"):
            send_text(sender, "No recent voice update to undo.")
            return

        voice_action = state_row["last_voice_action"]
        if isinstance(voice_action, str):
            voice_action = json.loads(voice_action)

        # Check 5-minute window
        action_ts = voice_action.get("timestamp")
        if action_ts:
            action_time = datetime.fromisoformat(action_ts)
            if datetime.now() - action_time > timedelta(minutes=5):
                send_text(sender, "⏰ UNDO window expired (5 minutes). The update cannot be reversed.")
                return

        task_id = voice_action.get("task_id")
        prev_progress = voice_action.get("prev_progress")
        update_id = voice_action.get("update_id")

        if not task_id:
            send_text(sender, "No recent voice update to undo.")
            return

        # Revert: delete the update record and restore task progress
        if update_id:
            try:
                supabase.table("updates").delete().eq("id", update_id).execute()
            except Exception as e:
                logger.warning(f"Could not delete update {update_id}: {e}")

        if prev_progress is not None:
            supabase.table("tasks").update(
                {"progress": prev_progress}
            ).eq("id", task_id).execute()

        # Clear the voice action
        supabase.table("wa_task_states").update(
            {"last_voice_action": None}
        ).eq("whatsapp_number", sender).execute()

        send_text(sender, "↩️ Done. Last voice update reversed.")
        logger.info(f"UNDO completed for {sender}, task {task_id}")

    except Exception as e:
        logger.error(f"UNDO failed for {sender}: {e}", exc_info=True)
        send_text(sender, "Couldn't undo right now — please try again.")

# ─────────────────────────────────────────────────────────────────────────────
# VOICE NOTE UNDO HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _capture_pre_update_snapshot(sender: str, transcript: str) -> dict | None:
    """
    Before processing a voice note, capture the current state of the
    most likely task being updated. This allows UNDO to restore it.

    Returns a dict with task_id, prev_progress, or None if we can't
    determine which task is being referenced.
    """
    try:
        from whatsapp.task_assignment import get_user_by_whatsapp
        from db import supabase, get_all_tasks

        user = get_user_by_whatsapp(sender)
        if not user:
            return None

        # Fetch all tasks assigned to this user
        tasks = get_all_tasks()
        user_tasks = [t for t in tasks if t.get('assigned_to') == user['id']
                      and t.get('status') != 'completed']

        if not user_tasks:
            return None

        # Try to fuzzy-match a task from the transcript
        from core.utils import resolve_task_from_list
        match = resolve_task_from_list(transcript, tasks, active_project_id=None)

        if match:
            # Get the latest update for this task to find update_id
            latest = supabase.table("updates").select("id").eq(
                "task_id", match["id"]
            ).order("timestamp", desc=True).limit(1).execute()

            return {
                "task_id": match["id"],
                "task_name": match.get("name"),
                "prev_progress": match.get("progress", 0) or 0,
                "latest_update_id": latest.data[0]["id"] if latest.data else None,
            }

        # If no match found, just store the first active task as fallback
        # The actual update ID will be captured post-processing
        return {
            "task_id": None,
            "prev_progress": None,
            "latest_update_id": None,
        }

    except Exception as e:
        logger.warning(f"Pre-update snapshot failed for {sender}: {e}")
        return None


def _store_voice_action(sender: str, snapshot: dict):
    """
    After a voice note is processed, store the action details in
    wa_task_states.last_voice_action for UNDO capability.

    The snapshot is enriched with the latest update_id (created by
    the update engine) and a timestamp.
    """
    try:
        from db import supabase
        from datetime import datetime
        import json

        if not snapshot or not snapshot.get("task_id"):
            # Try to get the task_id from the most recent update
            # by this user in the last 10 seconds
            from whatsapp.task_assignment import get_user_by_whatsapp
            user = get_user_by_whatsapp(sender)
            if user:
                latest = supabase.table("updates").select("id, task_id, progress").eq(
                    "employee_id", user["id"]
                ).order("timestamp", desc=True).limit(1).execute()
                if latest.data:
                    snapshot = snapshot or {}
                    snapshot["task_id"] = latest.data[0]["task_id"]
                    snapshot["update_id"] = latest.data[0]["id"]
                    if snapshot.get("prev_progress") is None:
                        snapshot["prev_progress"] = 0

        if not snapshot or not snapshot.get("task_id"):
            return

        # Get the actual new update_id (the one just created)
        from whatsapp.task_assignment import get_user_by_whatsapp
        user = get_user_by_whatsapp(sender)
        if user and not snapshot.get("update_id"):
            latest = supabase.table("updates").select("id").eq(
                "task_id", snapshot["task_id"]
            ).order("timestamp", desc=True).limit(1).execute()
            if latest.data:
                snapshot["update_id"] = latest.data[0]["id"]

        voice_action = {
            "task_id": snapshot.get("task_id"),
            "prev_progress": snapshot.get("prev_progress"),
            "update_id": snapshot.get("update_id") or snapshot.get("latest_update_id"),
            "timestamp": datetime.now().isoformat(),
        }

        # Upsert into wa_task_states
        supabase.table("wa_task_states").upsert({
            "whatsapp_number": sender,
            "last_voice_action": json.dumps(voice_action),
        }, on_conflict="whatsapp_number").execute()

        logger.info(f"Stored voice action for UNDO: {sender} → task {voice_action['task_id']}")

    except Exception as e:
        logger.warning(f"Failed to store voice action for {sender}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL RUN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)