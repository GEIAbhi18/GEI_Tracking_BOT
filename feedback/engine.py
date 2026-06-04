"""
Feedback Engine — Core Logic (WhatsApp Flows)
===============================================
Handles:
  - Initiating feedback sessions (sends WhatsApp Flow template)
  - Processing Flow form submissions (nfm_reply)
  - Score calculation, sentiment, escalation
  - Sheet write-back
  - Session lifecycle
"""

import logging
from datetime import datetime

from feedback.config import (
    NEGATIVE_KEYWORDS, STAGE_FLOW_SENT, STAGE_DONE,
)
from feedback.session_store import (
    create_session, get_session, set_session, remove_session,
    normalize_phone, has_active_session, enqueue_complaint,
    dequeue_next_complaint,
)
from feedback.messages import (
    message_b, feedback_in_progress_reply, session_cancelled,
)

logger = logging.getLogger(__name__)


def _send_wa(phone: str, text: str):
    """Send a WhatsApp text message using the existing task_assignment module."""
    from whatsapp.task_assignment import send_text
    send_text(phone, text)


def _ist_now() -> str:
    """Return current IST timestamp as string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Initiate Session ─────────────────────────────────────────────────────────

def initiate_feedback(complaint_data: dict) -> dict:
    """
    Called by the API when Apps Script triggers feedback collection.
    Creates session, sends WhatsApp Flow template to client.

    Returns: {"status": "ok"/"queued"/"error", "message": str}
    """
    phone = normalize_phone(complaint_data.get("clientPhone", ""))
    complaint_id = complaint_data.get("complaintId", "")

    if not phone or not complaint_id:
        return {"status": "error", "message": "Missing clientPhone or complaintId"}

    # Check if there's already an active session for this phone
    if has_active_session(phone):
        enqueue_complaint(phone, complaint_data)
        return {
            "status": "queued",
            "message": f"Active session exists for {phone}. Complaint {complaint_id} queued."
        }

    # Create new session
    session = create_session(complaint_data)
    set_session(phone, session)

    # Send WhatsApp Flow template message
    try:
        from feedback.flow_sender import send_flow_template
        sent = send_flow_template(
            phone=phone,
            client_name=session["clientName"],
            complaint_id=session["complaintId"],
            complaint_nature=session["complaintNature"],
            unit_no=session["unitNo"],
        )
        if not sent:
            logger.error(f"Failed to send Flow template for {complaint_id} → {phone}")
            # Don't remove session — we can retry via reminder
    except Exception as e:
        logger.error(f"Flow template send error for {complaint_id}: {e}", exc_info=True)

    # Mark feedback sent in building sheet (GEBB1 / GEBB2 / GETT)
    try:
        from feedback.sheets import update_building_sheet_feedback
        update_building_sheet_feedback(complaint_id, session.get("building", ""), {
            "Feedback Status": "Sent",
            "Feedback Sent At": session["feedbackSentAt"],
            "Reminder Count": "0",
        })
    except Exception as e:
        logger.error(f"Failed to mark feedback sent in building sheet: {e}")

    # Also write session to Pending Feedback sheet (backup)
    try:
        from feedback.sheets import save_session_to_sheet
        save_session_to_sheet(session)
    except Exception as e:
        logger.error(f"Failed to save session to Pending Feedback sheet: {e}")

    logger.info(f"Feedback initiated for {complaint_id} → {phone}")
    return {"status": "ok", "message": f"Feedback initiated for {complaint_id}"}


# ── Handle Flow Form Response ────────────────────────────────────────────────

def handle_flow_response(phone: str, response_data: dict) -> bool:
    """
    Process a WhatsApp Flow form submission (nfm_reply).

    Called from the webhook when an nfm_reply is received.
    Extracts scores, calculates overall score/sentiment/escalation,
    writes to sheets, sends thank you message.

    Args:
        phone: Sender's normalized phone number
        response_data: Parsed JSON from message.interactive.nfm_reply.response_json
                       Expected keys: resolution_rating, facility_team_rating,
                       overall_rating, comments (matching the WhatsApp Flow form)

    Returns:
        True if handled successfully, False if no active session
    """
    phone = normalize_phone(phone)
    session = get_session(phone)

    if not session:
        logger.warning(f"Flow response received from {phone} but no active session found — ignoring")
        _send_wa(phone, "This feedback session has expired or was already cleared. Thank you!")
        return False

    complaint_id = session.get("complaintId", "")

    # Extract scores from Flow response
    # Keys must match the WhatsApp Flow form field names exactly
    try:
        score_q1 = int(response_data.get("resolution_rating", 0))
        score_q2 = int(response_data.get("facility_team_rating", 0))
        score_q3 = int(response_data.get("overall_rating", 0))
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid score data in Flow response for {complaint_id}: {e}")
        score_q1 = score_q2 = score_q3 = 0

    tenant_comment = str(response_data.get("comments", "") or "").strip()
    if not tenant_comment:
        tenant_comment = "No comment"

    # Mark session as done
    session["stage"] = STAGE_DONE
    session["status"] = "received"
    set_session(phone, session)

    # Complete the feedback
    _complete_feedback(phone, session, score_q1, score_q2, score_q3, tenant_comment)
    return True


# ── Handle Text Reply (simplified for Flows) ────────────────────────────────

def handle_feedback_reply(phone: str, text: str) -> bool:
    """
    Process an incoming WhatsApp text message in the feedback context.

    With WhatsApp Flows, we no longer do conversational Q&A.
    If a user texts during an active Flow session, we send them
    a gentle reminder to use the Flow button.

    Returns True if the message was handled by the feedback engine,
    False if there's no active feedback session (fall through to main bot).
    """
    phone = normalize_phone(phone)
    session = get_session(phone)

    if not session:
        return False

    stage = session.get("stage", "")

    # Session is done — don't intercept
    if stage == STAGE_DONE:
        return False

    text_upper = text.strip().upper()

    # Handle STOP/CANCEL at any stage
    if text_upper in ("STOP", "CANCEL"):
        _handle_cancel(phone, session)
        return True

    # Active Flow session — let the user talk to the normal bot!
    # They can click the Flow button whenever they want.
    if stage == STAGE_FLOW_SENT:
        return False

    return True


# ── Cancel Handler ───────────────────────────────────────────────────────────

def _handle_cancel(phone: str, session: dict):
    """Client sent STOP or CANCEL."""
    _send_wa(phone, session_cancelled())

    # Mark as No Response in building sheet
    try:
        from feedback.sheets import update_building_sheet_feedback
        update_building_sheet_feedback(session["complaintId"], session.get("building", ""), {
            "Feedback Status": "No Response",
        })
    except Exception as e:
        logger.error(f"Failed to mark cancelled in building sheet: {e}")

    remove_session(phone)
    logger.info(f"Feedback cancelled for {session['complaintId']}")

    # Check if there are pending complaints for this phone
    _start_next_pending(phone)


# ── Feedback Completion ──────────────────────────────────────────────────────

def _complete_feedback(phone: str, session: dict,
                       score_q1: int, score_q2: int, score_q3: int,
                       tenant_comment: str):
    """
    Final step: calculate scores, determine sentiment, check escalation,
    write to sheets, send thank-you message.
    """
    complaint_id = session["complaintId"]
    now = _ist_now()

    # 1. Calculate overall score (hardcoded as per spec)
    overall_score = round(((score_q1 + score_q2 + score_q3) / 3) * 10) / 10

    # 2. Determine sentiment
    if overall_score >= 4:
        sentiment = "Happy"
    elif overall_score >= 3:
        sentiment = "Neutral"
    else:
        sentiment = "Unhappy"

    # 3. Escalation check
    escalation_status = "No"
    escalation_reason = ""

    low_score = overall_score <= 2
    negative_comment = any(
        k in tenant_comment.lower() for k in NEGATIVE_KEYWORDS
    )

    if low_score and negative_comment:
        escalation_status = "Open"
        escalation_reason = "Low Score + Negative Comment"
    elif low_score:
        escalation_status = "Open"
        escalation_reason = "Low Feedback Score"
    elif negative_comment:
        escalation_status = "Open"
        escalation_reason = "Negative Comment"

    should_escalate = low_score or negative_comment

    # 4. Write to building sheet (GEBB1 / GEBB2 / GETT)
    #    Column names must match the actual sheet headers exactly.
    feedback_data = {
        "Feedback Status": "Received",
        "Feedback Received At": now,
        "Resolution Score": score_q1,
        "Professionalism Score": score_q2,
        "Overall Feedback Score": score_q3,
        "Average Score": overall_score,
        "Remarks": tenant_comment,
        "Sentiment": sentiment,
        "Escalation Status": escalation_status,
        "Escalation Reason": escalation_reason,
    }

    sheet_write_ok = False
    try:
        from feedback.sheets import (
            update_building_sheet_feedback,
            update_master_feedback,
            append_escalation,
        )

        # 4a. Write to building sheet (GEBB1 / GEBB2 / GETT)
        update_building_sheet_feedback(
            complaint_id, session.get("building", ""), feedback_data
        )

        # 4b. Write to MASTER sheet (was missing — MASTER stayed at "Sent" forever)
        update_master_feedback(complaint_id, feedback_data)

        sheet_write_ok = True
        logger.info(f"Sheet write-back completed for {complaint_id}")

        # 5. Write escalation if needed
        if should_escalate:
            append_escalation({
                "Timestamp": now,
                "Complaint ID": complaint_id,
                "Building": session.get("building", ""),
                "Client Name / User": session.get("clientName", ""),
                "Unit No": session.get("unitNo", ""),
                "Complaint Nature": session.get("complaintNature", ""),
                "Complaint Details": session.get("complaintDetails", ""),
                "Overall Score": overall_score,
                "Sentiment": sentiment,
                "Customer Remarks": tenant_comment,
                "Escalation Reason": escalation_reason,
                "Escalation Status": "Open",
                "Action Taken": "",
            })
            logger.info(f"Escalation created for {complaint_id}: {escalation_reason}")

    except Exception as e:
        logger.error(f"Sheet write-back failed for {complaint_id}: {e}", exc_info=True)

    # 6. Send Thank You (Message B) — ALWAYS send, even if sheet write failed
    try:
        _send_wa(phone, message_b(session["clientName"], complaint_id, sheet_write_ok))
    except Exception as e:
        logger.error(f"Failed to send thank-you for {complaint_id}: {e}")

    logger.info(
        f"Feedback completed for {complaint_id}: "
        f"Q1={score_q1} Q2={score_q2} Q3={score_q3} "
        f"overall={overall_score} sentiment={sentiment}"
    )

    # 7. Clean up session — MUST happen even if sheet writes failed above.
    #    remove_session() is synchronous and removes from both memory + Pending Feedback sheet.
    try:
        remove_session(phone)
    except Exception as e:
        logger.error(f"Failed to remove session for {complaint_id}: {e}")

    # 8. Check for next pending complaint
    _start_next_pending(phone)


def _start_next_pending(phone: str):
    """If there are queued complaints, start the next one immediately."""
    next_complaint = dequeue_next_complaint(phone)
    if next_complaint:
        logger.info(f"Starting next queued feedback for {phone}: {next_complaint.get('complaintId')}")
        initiate_feedback(next_complaint)

