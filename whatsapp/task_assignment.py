"""
WhatsApp Task Assignment Module
================================
Handles the Kanav → Asif task assignment flow:
  - Sending interactive button messages when Kanav creates a task
  - Accept / Reject / Edit-Date response handling
  - DB state persistence (survives Render restarts)
  - Notifying Kanav of every outcome
"""

import os
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Env vars (loaded by whatsapp_webhook.py at startup) ──────────────────────
WHATSAPP_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
WA_API_BASE = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}"


# ─────────────────────────────────────────────────────────────────────────────
# LOW-LEVEL WhatsApp API HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _post_wa(payload: dict) -> bool:
    """POST any payload to the WhatsApp messages endpoint. Returns True on success."""
    if not WHATSAPP_ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WA Task Assignment: Missing META_ACCESS_TOKEN or PHONE_NUMBER_ID")
        return False
    url = f"{WA_API_BASE}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        logger.info(f"WA API {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"WA API error: {e}")
        return False


def send_text(to: str, body: str) -> bool:
    """Send a plain-text WhatsApp message."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    return _post_wa(payload)


def send_interactive_buttons(to: str, body: str, buttons: list) -> bool:
    """
    Send an interactive button message.
    buttons: [{"id": "BUTTON_ID", "title": "Button Label"}, ...]
    Max 3 buttons, title ≤ 20 chars, id ≤ 256 chars.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons
                ]
            },
        },
    }
    return _post_wa(payload)

def _send_document_wa(to: str, file_path: str) -> bool:
    """Upload a file to WhatsApp and send it as a document."""
    if not WHATSAPP_ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WA Task Assignment: Missing META_ACCESS_TOKEN or PHONE_NUMBER_ID")
        return False
        
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False

    # Step 1: Upload media
    upload_url = f"{WA_API_BASE}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    
    file_name = os.path.basename(file_path)
    mime_type = "application/pdf" if file_name.endswith(".pdf") else "application/octet-stream"
    
    try:
        with open(file_path, "rb") as f:
            files = {
                "file": (file_name, f, mime_type)
            }
            data = {"messaging_product": "whatsapp"}
            upload_res = requests.post(upload_url, headers=headers, data=data, files=files, timeout=30)
            upload_res.raise_for_status()
            media_id = upload_res.json().get("id")
    except Exception as e:
        logger.error(f"WA API media upload error: {e}")
        return False

    if not media_id:
        logger.error("Failed to get media_id from WhatsApp upload response")
        return False

    # Step 2: Send document message
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": file_name
        }
    }
    return _post_wa(payload)


# ─────────────────────────────────────────────────────────────────────────────
# DB HELPERS (imported lazily to avoid circular imports at module load)
# ─────────────────────────────────────────────────────────────────────────────

def _get_supabase():
    from db import supabase
    return supabase


def get_user_by_whatsapp(phone: str):
    """Return user row by whatsapp_number. Phone in E.164 (e.g. 919xxxxxxxx or +919xxxxxxxx)."""
    try:
        clean_phone = str(phone).lstrip("+")
        r = _get_supabase().table("users").select("*").or_(f"whatsapp_number.eq.{clean_phone},whatsapp_number.eq.+{clean_phone}").execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"get_user_by_whatsapp error: {e}")
        return None


def get_task_by_id(task_id: str):
    """Return full task row with project and assignee details."""
    try:
        r = _get_supabase().table("tasks").select(
            "*, projects(name), assigned_to_user:users!assigned_to(name, whatsapp_number), "
            "assigned_by_user:users!assigned_by(name, whatsapp_number)"
        ).eq("id", task_id).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"get_task_by_id error: {e}")
        return None


def update_task_assignment(task_id: str, **fields) -> bool:
    """Update one or more assignment-related fields on a task."""
    try:
        _get_supabase().table("tasks").update(fields).eq("id", task_id).execute()
        return True
    except Exception as e:
        logger.error(f"update_task_assignment error: {e}")
        return False


# ── Persistent WhatsApp state (survives Render restarts) ─────────────────────

def get_wa_state(phone: str):
    """Get pending WA conversation state for a phone number."""
    try:
        r = _get_supabase().table("wa_task_states").select("*").eq("whatsapp_number", phone).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"get_wa_state error: {e}")
        return None


def set_wa_state(phone: str, action: str, task_id: str):
    """Upsert WA conversation state for a phone number."""
    try:
        _get_supabase().table("wa_task_states").upsert({
            "whatsapp_number": phone,
            "action": action,
            "task_id": task_id,
            "updated_at": datetime.utcnow().isoformat(),
        }, on_conflict="whatsapp_number").execute()
    except Exception as e:
        logger.error(f"set_wa_state error: {e}")


def clear_wa_state(phone: str):
    """Remove WA conversation state for a phone number."""
    try:
        _get_supabase().table("wa_task_states").delete().eq("whatsapp_number", phone).execute()
    except Exception as e:
        logger.error(f"clear_wa_state error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TASK CREATION TRIGGER
# ─────────────────────────────────────────────────────────────────────────────

def on_task_created_by_kanav(task_id: str, task_name: str, project_name: str,
                              due_date: str, creator_wa: str, assignee_wa: str,
                              kanav_wa: str = None, creator_name: str = "A team member", assignee_name: str = "Team Member"):
    """
    Called after a task creator creates a task.
    Sends interactive approval message to the assignee and confirms to creator.
    """
    confirm_wa = creator_wa or kanav_wa
    body = (
        f"*{creator_name}* created a task for you:\n\n"
        f"📌 Task: {task_name}\n"
        f"📂 Project: {project_name}\n"
        f"📅 Planned completion date: {due_date}\n\n"
        f"Do you agree?"
    )
    # Button IDs must be ≤ 256 chars. UUIDs are 36 chars.
    buttons = [
        {"id": f"ACCEPT_TASK_{task_id}",   "title": "✅ Accept"},
        {"id": f"REJECT_TASK_{task_id}",   "title": "❌ Reject"},
        {"id": f"EDITDATE_TASK_{task_id}", "title": "📅 Edit Date"},
    ]

    sent = send_interactive_buttons(assignee_wa, body, buttons)

    if sent:
        logger.info(f"Task assignment message sent to {assignee_name} ({assignee_wa}) for task {task_id}")
        # Mark assignment as pending in DB
        update_task_assignment(task_id, assignment_status="pending_acceptance")
        # Confirm to Creator
        if confirm_wa:
            send_text(confirm_wa, f"✅ Task Created.\n📩 Message sent to *{assignee_name}* for approval.")
    else:
        logger.error(f"Failed to send task assignment message to {assignee_name} ({assignee_wa})")
        if confirm_wa:
            send_text(confirm_wa, f"✅ Task Created.\n⚠️ Could not reach *{assignee_name}* on WhatsApp. Please notify manually.")


# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOK RESPONSE HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def handle_button_reply(sender_phone: str, button_id: str):
    """
    Route an interactive button_reply to the correct handler.
    Called from whatsapp_webhook.py when message type == 'interactive'.
    """
    logger.info(f"Button reply from {sender_phone}: {button_id}")

    if button_id.startswith("ACCEPT_TASK_"):
        task_id = button_id[len("ACCEPT_TASK_"):]
        _handle_accept(sender_phone, task_id)

    elif button_id.startswith("REJECT_TASK_"):
        task_id = button_id[len("REJECT_TASK_"):]
        _handle_reject_step1(sender_phone, task_id)

    elif button_id.startswith("EDITDATE_TASK_"):
        task_id = button_id[len("EDITDATE_TASK_"):]
        _handle_editdate_step1(sender_phone, task_id)

    else:
        logger.warning(f"Unknown button_id from {sender_phone}: {button_id}")


def handle_text_reply(sender_phone: str, text: str) -> bool:
    """
    Handle a plain-text reply when the sender is in a pending WA state
    (e.g. rejection reason, new date entry).

    Returns True if handled (should NOT be passed to the main bot engine),
    False if not handled (caller should fall through to main engine).
    """
    state = get_wa_state(sender_phone)
    if not state:
        # Check for shorthand "yes" / "no" responses
        # Only apply if the user has a recent pending task
        return _check_yes_no_shorthand(sender_phone, text)

    action = state.get("action")
    task_id = state.get("task_id")

    if action == "awaiting_rejection_reason":
        _handle_reject_step2(sender_phone, task_id, text)
        return True

    elif action == "awaiting_new_date":
        _handle_editdate_step2(sender_phone, task_id, text)
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL FLOW HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_creator_number(task: dict):
    """Extract creator's WhatsApp number from a task's assigned_by_user or created_by_user field."""
    try:
        creator = task.get("assigned_by_user") or task.get("created_by_user") or {}
        if isinstance(creator, list):
            creator = creator[0] if creator else {}
        return creator.get("whatsapp_number")
    except Exception:
        return None


def _handle_accept(sender_phone: str, task_id: str):
    """Assignee clicked Accept."""
    sender = get_user_by_whatsapp(sender_phone)
    task = get_task_by_id(task_id)

    if not task:
        send_text(sender_phone, "Couldn't find that task — it may have been removed.")
        return

    # Idempotency: skip if already accepted
    if task.get("assignment_status") == "accepted":
        send_text(sender_phone, "ℹ️ You have already accepted this task.")
        return

    # Update DB
    accepted_by = sender["id"] if sender else None
    update_task_assignment(task_id,
                           status="Accepted",
                           assignment_status="accepted",
                           accepted_by=accepted_by)
    clear_wa_state(sender_phone)

    # Confirm to Assignee
    send_text(sender_phone, "✅ You accepted the task.")

    # Notify Creator
    creator_number = _get_creator_number(task)
    if creator_number:
        task_name = task.get("name", "Team Task")
        assignee_name = sender.get("name", "Assignee") if sender else "Assignee"
        send_text(creator_number, f"✅ Task *'{task_name}'* has been accepted by *{assignee_name}*.")
    else:
        logger.warning(f"Could not find creator's WhatsApp number to notify for task {task_id}")


def _handle_reject_step1(sender_phone: str, task_id: str):
    """Assignee clicked Reject — ask for reason."""
    task = get_task_by_id(task_id)
    if not task:
        send_text(sender_phone, "Couldn't find that task — it may have been removed.")
        return

    if task.get("assignment_status") == "rejected":
        send_text(sender_phone, "ℹ️ You have already rejected this task.")
        return

    # Mark as pending reason
    update_task_assignment(task_id, assignment_status="rejected_pending_reason")
    # Store state so next text is treated as rejection reason
    set_wa_state(sender_phone, "awaiting_rejection_reason", task_id)

    send_text(sender_phone, "Please provide reason for rejection.")


def _handle_reject_step2(sender_phone: str, task_id: str, reason: str):
    """Assignee sent rejection reason."""
    sender = get_user_by_whatsapp(sender_phone)
    task = get_task_by_id(task_id)

    # Update DB with final rejected status + reason
    update_task_assignment(task_id,
                           assignment_status="rejected",
                           rejection_reason=reason)
    clear_wa_state(sender_phone)

    # Notify Creator
    creator_number = _get_creator_number(task) if task else None
    if creator_number:
        task_name = task.get("name", "the task")
        assignee_name = sender.get("name", "Assignee") if sender else "Assignee"
        send_text(creator_number,
                  f"❌ Task *'{task_name}'* has been rejected by *{assignee_name}* due to: {reason}")
    else:
        logger.warning(f"Could not find creator's number for rejection notification, task {task_id}")


def _handle_editdate_step1(sender_phone: str, task_id: str):
    """Assignee clicked Edit Date — ask for new date."""
    task = get_task_by_id(task_id)
    if not task:
        send_text(sender_phone, "Couldn't find that task — it may have been removed.")
        return

    update_task_assignment(task_id, assignment_status="awaiting_new_date")
    set_wa_state(sender_phone, "awaiting_new_date", task_id)

    send_text(sender_phone, "Please enter new proposed completion date (YYYY-MM-DD).")


def _handle_editdate_step2(sender_phone: str, task_id: str, date_text: str):
    """Asif submitted a new date."""
    import re
    sender = get_user_by_whatsapp(sender_phone)
    task = get_task_by_id(task_id)

    # Validate YYYY-MM-DD format
    date_text = date_text.strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_text):
        send_text(sender_phone,
                  "That date format didn't work — please use YYYY-MM-DD.\nExample: 2026-05-15")
        return

    # Optional: validate it's a real calendar date
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        send_text(sender_phone, "That doesn't look like a real date.\nPlease enter a date like 2026-05-15")
        return

    # Update DB: new deadline + accept
    accepted_by = sender["id"] if sender else None
    update_task_assignment(task_id,
                           status="Accepted",
                           assignment_status="accepted",
                           accepted_by=accepted_by,
                           deadline=date_text)
    clear_wa_state(sender_phone)

    # Confirm to Assignee
    send_text(sender_phone, f"✅ Task accepted with updated date: {date_text}")

    # Notify Creator
    creator_number = _get_creator_number(task) if task else None
    if creator_number:
        task_name = task.get("name", "the task") if task else "the task"
        assignee_name = sender.get("name", "Assignee") if sender else "Assignee"
        send_text(creator_number,
                  f"✅ Task *'{task_name}'* has been accepted by *{assignee_name}*.\n📅 New completion date: {date_text}")
    else:
        logger.warning(f"Could not notify creator for edit-date on task {task_id}")


def _check_yes_no_shorthand(sender_phone: str, text: str) -> bool:
    """
    If user has a pending_acceptance task, allow 'yes'→accept / 'no'→reject shorthand.
    Returns True if handled.
    """
    t = text.strip().lower()
    if t not in ("yes", "no"):
        return False

    # Look for a task in pending_acceptance for this phone
    try:
        user = get_user_by_whatsapp(sender_phone)
        if not user:
            return False
        r = _get_supabase().table("tasks").select("id").eq(
            "assigned_to", user["id"]
        ).eq("assignment_status", "pending_acceptance").order(
            "created_at", desc=True
        ).limit(1).execute()

        if not r.data:
            return False

        task_id = r.data[0]["id"]

        if t == "yes":
            _handle_accept(sender_phone, task_id)
        else:
            _handle_reject_step1(sender_phone, task_id)
        return True
    except Exception as e:
        logger.error(f"yes/no shorthand error: {e}")
        return False
