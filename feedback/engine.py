"""
Feedback Engine — Core Logic
=============================
Handles the conversational flow:
  - Initiating feedback sessions
  - Processing incoming client replies
  - Score validation & storage
  - Feedback completion (scoring, sentiment, escalation, sheet write-back)
"""

import logging
from datetime import datetime

from feedback.config import (
    VALID_SCORES, MAX_INVALID_ATTEMPTS, NEGATIVE_KEYWORDS,
    STAGE_AWAITING_START, STAGE_Q1, STAGE_Q2, STAGE_Q3, STAGE_Q4, STAGE_DONE,
)
from feedback.session_store import (
    create_session, get_session, set_session, remove_session,
    normalize_phone, has_active_session, enqueue_complaint,
    dequeue_next_complaint, has_pending_complaints,
)
from feedback.messages import (
    message_a, question_1, question_2, question_3, question_4,
    message_b, invalid_score_prompt, session_cancelled,
    complete_feedback_first,
)

logger = logging.getLogger(__name__)


def _send_wa(phone: str, text: str):
    """Send a WhatsApp message using the existing task_assignment module."""
    from whatsapp.task_assignment import send_text
    send_text(phone, text)


# ── Initiate Session ─────────────────────────────────────────────────────────

def initiate_feedback(complaint_data: dict) -> dict:
    """
    Called by the API when Apps Script triggers feedback collection.
    Creates session, sends Message A to client.

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

    # Send Message A
    msg = message_a(
        client_name=session["clientName"],
        complaint_id=session["complaintId"],
        complaint_nature=session["complaintNature"],
        unit_no=session["unitNo"],
    )
    _send_wa(phone, msg)

    # Mark feedback sent in MASTER sheet
    try:
        from feedback.sheets import mark_feedback_sent
        mark_feedback_sent(complaint_id, session["feedbackSentAt"])
    except Exception as e:
        logger.error(f"Failed to mark feedback sent in sheet: {e}")

    logger.info(f"Feedback initiated for {complaint_id} → {phone}")
    return {"status": "ok", "message": f"Feedback initiated for {complaint_id}"}


# ── Handle Incoming Reply ────────────────────────────────────────────────────

def handle_feedback_reply(phone: str, text: str) -> bool:
    """
    Process an incoming WhatsApp text message in the feedback context.

    Returns True if the message was handled by the feedback engine,
    False if there's no active feedback session (fall through to main bot).
    """
    phone = normalize_phone(phone)
    session = get_session(phone)

    if not session:
        return False

    stage = session.get("stage", "")

    # Session is done — do not respond
    if stage == STAGE_DONE:
        return True

    text_stripped = text.strip()
    text_upper = text_stripped.upper()

    # Handle STOP/CANCEL at any stage
    if text_upper in ("STOP", "CANCEL"):
        _handle_cancel(phone, session)
        return True

    # Route based on current stage
    if stage == STAGE_AWAITING_START:
        _handle_start(phone, session, text_upper)
    elif stage == STAGE_Q1:
        _handle_score(phone, session, text_stripped, "score_q1", 1, STAGE_Q2, question_2)
    elif stage == STAGE_Q2:
        _handle_score(phone, session, text_stripped, "score_q2", 2, STAGE_Q3, question_3)
    elif stage == STAGE_Q3:
        _handle_score(phone, session, text_stripped, "score_q3", 3, STAGE_Q4, question_4)
    elif stage == STAGE_Q4:
        _handle_comment(phone, session, text_stripped)

    return True


# ── Stage Handlers ───────────────────────────────────────────────────────────

def _handle_start(phone: str, session: dict, text: str):
    """Client replied to Message A — send Q1 regardless of reply content."""
    session["sessionStarted"] = True
    session["stage"] = STAGE_Q1
    session["invalidAttempts"] = 0
    set_session(phone, session)

    _send_wa(phone, question_1(session["complaintId"]))
    logger.info(f"Feedback session started for {session['complaintId']}")


def _handle_score(phone: str, session: dict, text: str,
                  score_key: str, q_num: int,
                  next_stage: str, next_question_fn):
    """Handle a score answer for Q1/Q2/Q3."""
    if text in VALID_SCORES:
        session[score_key] = int(text)
        session["invalidAttempts"] = 0
        session["stage"] = next_stage
        set_session(phone, session)

        # Send next question
        if next_question_fn == question_4:
            _send_wa(phone, next_question_fn())
        else:
            _send_wa(phone, next_question_fn())
        logger.info(f"{score_key}={text} for {session['complaintId']}")
    else:
        # Invalid answer
        session["invalidAttempts"] = session.get("invalidAttempts", 0) + 1
        if session["invalidAttempts"] >= MAX_INVALID_ATTEMPTS:
            # Store 0 and move forward
            session[score_key] = 0
            session["invalidAttempts"] = 0
            session["stage"] = next_stage
            set_session(phone, session)

            if next_question_fn == question_4:
                _send_wa(phone, next_question_fn())
            else:
                _send_wa(phone, next_question_fn())
            logger.info(f"{score_key}=0 (max invalid) for {session['complaintId']}")
        else:
            set_session(phone, session)
            _send_wa(phone, invalid_score_prompt(q_num))


def _handle_comment(phone: str, session: dict, text: str):
    """Handle Q4 (free text comment)."""
    if not text or text.upper() == "SKIP":
        session["tenant_comment"] = "No comment"
    else:
        session["tenant_comment"] = text

    session["stage"] = STAGE_DONE
    set_session(phone, session)

    # Complete the feedback
    _complete_feedback(phone, session)


def _handle_cancel(phone: str, session: dict):
    """Client sent STOP or CANCEL."""
    _send_wa(phone, session_cancelled())

    # Mark as No Response in sheet
    try:
        from feedback.sheets import update_master_feedback
        update_master_feedback(session["complaintId"], {
            "Feedback Status": "No Response",
        })
    except Exception as e:
        logger.error(f"Failed to mark cancelled in sheet: {e}")

    remove_session(phone)
    logger.info(f"Feedback cancelled for {session['complaintId']}")

    # Check if there are pending complaints for this phone
    _start_next_pending(phone)


# ── Feedback Completion ──────────────────────────────────────────────────────

def _complete_feedback(phone: str, session: dict):
    """
    Final step: calculate scores, determine sentiment, check escalation,
    write to sheets, send thank-you message.
    """
    complaint_id = session["complaintId"]

    # 1. Calculate overall score
    scores = []
    for key in ("score_q1", "score_q2", "score_q3"):
        val = session.get(key)
        if val is not None and val > 0:
            scores.append(val)

    if scores:
        overall_score = round(sum(scores) / len(scores), 1)
    else:
        overall_score = 0

    # 2. Determine sentiment
    if overall_score >= 4:
        sentiment = "Happy"
    elif overall_score == 3:
        sentiment = "Neutral"
    else:
        sentiment = "Unhappy"

    # 3. Escalation check
    escalation_status = "No"
    escalation_reason = ""

    low_score = overall_score <= 2
    negative_comment = False
    comment = (session.get("tenant_comment") or "").lower()
    for keyword in NEGATIVE_KEYWORDS:
        if keyword in comment:
            negative_comment = True
            break

    if low_score and negative_comment:
        escalation_status = "Open"
        escalation_reason = "Low Score + Negative Comment"
    elif low_score:
        escalation_status = "Open"
        escalation_reason = "Low Feedback Score"
    elif negative_comment:
        escalation_status = "Open"
        escalation_reason = "Negative Comment"

    now = datetime.now().isoformat()

    # 4. Write to MASTER sheet
    feedback_data = {
        "Feedback Status": "Received",
        "Feedback Received At": now,
        "Overall Feedback Score": overall_score,
        "Score Q1": session.get("score_q1", 0),
        "Score Q2": session.get("score_q2", 0),
        "Score Q3": session.get("score_q3", 0),
        "Sentiment": sentiment,
        "Tenant Comment": session.get("tenant_comment", "No comment"),
        "Escalation Status": escalation_status,
        "Escalation Reason": escalation_reason,
        "Reminder Count": session.get("reminderCount", 0),
        "Last Reminder At": session.get("lastReminderAt", ""),
    }

    try:
        from feedback.sheets import (
            update_master_feedback, update_building_sheet_feedback,
            append_escalation,
        )

        update_master_feedback(complaint_id, feedback_data)
        update_building_sheet_feedback(complaint_id, session.get("building", ""), feedback_data)

        # 5. Write escalation if needed
        if escalation_status == "Open":
            append_escalation({
                "Timestamp": now,
                "Complaint ID": complaint_id,
                "Building": session.get("building", ""),
                "Client Name": session.get("clientName", ""),
                "Unit No": session.get("unitNo", ""),
                "Complaint Nature": session.get("complaintNature", ""),
                "Complaint Details": "",
                "Overall Score": overall_score,
                "Sentiment": sentiment,
                "Tenant Comment": session.get("tenant_comment", ""),
                "Escalation Reason": escalation_reason,
                "Escalation Status": "Open",
                "Action Taken": "",
            })
            logger.info(f"Escalation created for {complaint_id}: {escalation_reason}")

    except Exception as e:
        logger.error(f"Sheet write-back failed for {complaint_id}: {e}", exc_info=True)

    # 6. Send Thank You (Message B)
    _send_wa(phone, message_b(session["clientName"], complaint_id))
    logger.info(f"Feedback completed for {complaint_id}: score={overall_score}, sentiment={sentiment}")

    # Clean up session
    remove_session(phone)

    # Check for next pending complaint
    _start_next_pending(phone)


def _start_next_pending(phone: str):
    """If there are queued complaints, start the next one immediately."""
    next_complaint = dequeue_next_complaint(phone)
    if next_complaint:
        logger.info(f"Starting next queued feedback for {phone}: {next_complaint.get('complaintId')}")
        initiate_feedback(next_complaint)


# ── Current Question Text Helper ─────────────────────────────────────────────

def get_current_question_text(session: dict) -> str:
    """Return the text of the current question for re-prompting."""
    stage = session.get("stage", "")
    cid = session.get("complaintId", "")

    if stage == STAGE_Q1:
        return question_1(cid)
    elif stage == STAGE_Q2:
        return question_2()
    elif stage == STAGE_Q3:
        return question_3()
    elif stage == STAGE_Q4:
        return question_4()
    elif stage == STAGE_AWAITING_START:
        return message_a(
            session.get("clientName", ""),
            cid,
            session.get("complaintNature", ""),
            session.get("unitNo", ""),
        )
    return ""
