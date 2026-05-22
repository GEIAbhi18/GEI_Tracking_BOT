"""
Feedback Reminder Scheduler
============================
Checks for sessions that need reminders and sends them.
Called periodically by a cron/scheduler.
"""

import logging
from datetime import datetime, timedelta

from feedback.config import (
    REMINDER_1_DELAY_SECONDS,
    REMINDER_2_DELAY_SECONDS,
    STAGE_AWAITING_START,
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
    
    Reminder Logic:
      - 6 hours after feedbackSentAt → Reminder 1 (if still awaiting_start)
      - 12 hours after feedbackSentAt → Reminder 2 (if still awaiting_start)
      - After Reminder 2 → mark as "No Response", close session
    """
    sessions = get_all_active_sessions()
    now = datetime.now()

    for session in sessions:
        stage = session.get("stage", "")
        
        # Only send reminders for sessions awaiting start
        if stage != STAGE_AWAITING_START:
            continue

        phone = normalize_phone(session.get("clientPhone", ""))
        complaint_id = session.get("complaintId", "")
        reminder_count = session.get("reminderCount", 0)
        feedback_sent_at = session.get("feedbackSentAt", "")

        if not feedback_sent_at:
            continue

        try:
            sent_time = datetime.fromisoformat(feedback_sent_at)
        except (ValueError, TypeError):
            logger.warning(f"Invalid feedbackSentAt for {complaint_id}: {feedback_sent_at}")
            continue

        elapsed = (now - sent_time).total_seconds()

        if reminder_count >= 2:
            # Already sent 2 reminders — mark as No Response
            _mark_no_response(phone, session)
            continue

        # Determine if reminder is due
        if reminder_count == 0 and elapsed >= REMINDER_1_DELAY_SECONDS:
            _send_reminder(phone, session, reminder_num=1)
        elif reminder_count == 1 and elapsed >= REMINDER_2_DELAY_SECONDS:
            _send_reminder(phone, session, reminder_num=2)


def _send_reminder(phone: str, session: dict, reminder_num: int):
    """Send a reminder message and update session."""
    complaint_id = session["complaintId"]
    now = datetime.now().isoformat()

    msg = reminder_message(session["clientName"], complaint_id)
    _send_wa(phone, msg)

    session["reminderCount"] = reminder_num
    session["lastReminderAt"] = now
    set_session(phone, session)

    # Update sheet
    try:
        from feedback.sheets import update_master_feedback
        update_master_feedback(complaint_id, {
            "Reminder Count": reminder_num,
            "Last Reminder Sent At": now,
        })
    except Exception as e:
        logger.error(f"Failed to update reminder in sheet: {e}")

    logger.info(f"Reminder {reminder_num} sent for {complaint_id} → {phone}")


def _mark_no_response(phone: str, session: dict):
    """Mark session as No Response after max reminders."""
    complaint_id = session["complaintId"]

    try:
        from feedback.sheets import update_master_feedback
        update_master_feedback(complaint_id, {
            "Feedback Status": "No Response",
            "Reminder Count": session.get("reminderCount", 2),
            "Last Reminder Sent At": session.get("lastReminderAt", ""),
        })
    except Exception as e:
        logger.error(f"Failed to mark No Response in sheet: {e}")

    remove_session(phone)
    logger.info(f"Marked No Response for {complaint_id}")
