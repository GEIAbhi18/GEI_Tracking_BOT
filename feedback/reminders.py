"""
Feedback Reminder Scheduler
============================
Checks for sessions that need reminders and sends them.
Uses Google Sheets 'Pending Feedback' as source of truth (survives server restarts).
Called periodically by APScheduler (every 15 minutes).
"""

import logging
from datetime import datetime, timedelta

from feedback.config import (
    REMINDER_INTERVAL_HOURS,
    MAX_REMINDERS,
    STAGE_FLOW_SENT,
    STAGE_DONE,
)
from feedback.session_store import (
    get_all_active_sessions, set_session, remove_session, normalize_phone,
)
from feedback.messages import reminder_message

logger = logging.getLogger(__name__)


def _send_wa(phone: str, text: str):
    """Send a WhatsApp message."""
    from whatsapp.task_assignment import send_text
    send_text(phone, text)


def check_and_send_reminders():
    """
    Check all active sessions and send reminders if due.

    Reminder Logic (WhatsApp Flows):
      - Every REMINDER_INTERVAL_HOURS (default 6h) after feedbackSentAt
      - Max MAX_REMINDERS (default 2) reminders total
      - After max reminders → mark as "No Response", close session
      - Plain text reminder (no Flow button) — user taps button in original message

    Source of truth: reads from Pending Feedback sheet on each run
    to survive server restarts.
    """
    # Reload sessions from sheet to ensure we have the latest state
    try:
        from feedback.sheets import load_pending_sessions
        pending = load_pending_sessions()
    except Exception as e:
        logger.error(f"Failed to load pending sessions for reminder check: {e}")
        # Fall back to in-memory sessions
        pending = get_all_active_sessions()

    now = datetime.now()
    reminder_interval_seconds = REMINDER_INTERVAL_HOURS * 3600

    for session in pending:
        stage = session.get("stage", "")

        # Only send reminders for sessions where Flow template was sent
        if stage not in (STAGE_FLOW_SENT, "awaiting_start", "sent"):
            continue

        phone = normalize_phone(session.get("clientPhone", ""))
        complaint_id = session.get("complaintId", "")
        reminder_count = int(session.get("reminderCount", 0) or 0)
        feedback_sent_at = session.get("feedbackSentAt", "")

        if not feedback_sent_at or not phone:
            continue

        try:
            # Try multiple datetime formats
            sent_time = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
                try:
                    sent_time = datetime.strptime(str(feedback_sent_at), fmt)
                    break
                except ValueError:
                    continue
            if sent_time is None:
                sent_time = datetime.fromisoformat(str(feedback_sent_at))
        except (ValueError, TypeError):
            logger.warning(f"Invalid feedbackSentAt for {complaint_id}: {feedback_sent_at}")
            continue

        elapsed = (now - sent_time).total_seconds()

        if reminder_count >= MAX_REMINDERS:
            # Already sent max reminders — mark as No Response
            _mark_no_response(phone, session)
            continue

        # Check if reminder is due (every REMINDER_INTERVAL_HOURS after sent)
        next_reminder_due_at = reminder_interval_seconds * (reminder_count + 1)
        if elapsed >= next_reminder_due_at:
            _send_reminder(phone, session, reminder_count + 1)


def _send_reminder(phone: str, session: dict, reminder_num: int):
    """Send a reminder message and update session + sheet."""
    complaint_id = session["complaintId"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    msg = reminder_message(session.get("clientName", ""), complaint_id)
    _send_wa(phone, msg)

    session["reminderCount"] = reminder_num
    session["lastReminderAt"] = now
    set_session(phone, session)

    # Update reminder count in sheet
    try:
        from feedback.sheets import update_pending_reminder_count
        update_pending_reminder_count(phone, reminder_num, now)
    except Exception as e:
        logger.error(f"Failed to update reminder count in sheet: {e}")

    # Also update MASTER sheet
    try:
        from feedback.sheets import update_master_feedback
        update_master_feedback(complaint_id, {
            "Reminder Count": reminder_num,
            "Last Reminder Sent At": now,
        })
    except Exception as e:
        logger.error(f"Failed to update reminder in MASTER sheet: {e}")

    logger.info(f"Reminder {reminder_num} sent for {complaint_id} → {phone}")


def _mark_no_response(phone: str, session: dict):
    """Mark session as No Response after max reminders."""
    complaint_id = session.get("complaintId", "")

    try:
        from feedback.sheets import update_master_feedback
        update_master_feedback(complaint_id, {
            "Feedback Status": "No Response",
            "Reminder Count": session.get("reminderCount", MAX_REMINDERS),
            "Last Reminder Sent At": session.get("lastReminderAt", ""),
        })
    except Exception as e:
        logger.error(f"Failed to mark No Response in sheet: {e}")

    remove_session(phone)
    logger.info(f"Marked No Response for {complaint_id} (max reminders reached)")
