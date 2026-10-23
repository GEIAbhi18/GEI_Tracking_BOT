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
    # --- Fix swapped fields from Google Apps Script ---
    c_id_raw = str(complaint_data.get("complaintId", "")).strip()
    bld_raw = str(complaint_data.get("building", "")).strip()
    
    if c_id_raw.isdigit() and len(c_id_raw) >= 10 and ('-' in bld_raw):
        real_phone = c_id_raw
        real_complaint = bld_raw
        
        prefix = real_complaint.split('-')[0].upper()
        if prefix == 'B1':
            real_building = "GEBB1"
        elif prefix == 'B2':
            real_building = "GEBB2"
        elif prefix in ('TT', 'T1'):
            real_building = "GETT"
        else:
            real_building = bld_raw
            
        logger.warning(f"Auto-correcting swapped fields in initiate_feedback: phone={real_phone}, complaintId={real_complaint}, building={real_building}")
        
        complaint_data["clientPhone"] = real_phone
        complaint_data["complaintId"] = real_complaint
        complaint_data["building"] = real_building
    # --------------------------------------------------

    phone = normalize_phone(complaint_data.get("clientPhone", ""))
    complaint_id = complaint_data.get("complaintId", "")

    if not phone or not complaint_id:
        return {"status": "error", "message": "Missing clientPhone or complaintId"}

    print(f"[FEEDBACK] initiate_feedback called for {complaint_id} → {phone}", flush=True)

    # Check if there's already an active session for this phone
    if has_active_session(phone):
        existing_session = get_session(phone)
        if existing_session and existing_session.get("complaintId") == complaint_id:
            # Re-initiating for the same complaint — re-send Flow template message directly
            print(f"[FEEDBACK] Re-initiating active session for {complaint_id} → re-sending Flow template", flush=True)
            try:
                from feedback.flow_sender import send_flow_template
                send_flow_template(
                    phone=phone,
                    client_name=existing_session.get("clientName", ""),
                    complaint_id=complaint_id,
                    complaint_nature=existing_session.get("complaintNature", ""),
                    unit_no=existing_session.get("unitNo", ""),
                    complaint_details=existing_session.get("complaintDetails", ""),
                    closed_at=existing_session.get("closedAt", ""),
                )
            except Exception as re_err:
                logger.error(f"Error re-sending flow template for {complaint_id}: {re_err}")
            return {
                "status": "ok",
                "message": f"Feedback template re-sent for {complaint_id}"
            }

        enqueue_complaint(phone, complaint_data)
        print(f"[FEEDBACK] Session already active for {phone} — complaint {complaint_id} queued", flush=True)
        return {
            "status": "queued",
            "message": f"Active session exists for {phone}. Complaint {complaint_id} queued."
        }

    # Create new session
    session = create_session(complaint_data)
    set_session(phone, session)  # Also triggers async backup to Pending Feedback sheet
    print(f"[FEEDBACK] Session created for {complaint_id} (stage={session['stage']})", flush=True)

    # Send WhatsApp Flow template message
    try:
        from feedback.flow_sender import send_flow_template
        sent = send_flow_template(
            phone=phone,
            client_name=session["clientName"],
            complaint_id=session["complaintId"],
            complaint_nature=session["complaintNature"],
            unit_no=session["unitNo"],
            complaint_details=session.get("complaintDetails", ""),
            closed_at=session.get("closedAt", "") or complaint_data.get("closedAt", ""),
        )
        if not sent:
            print(f"[FEEDBACK] ⚠️ Flow template send FAILED for {complaint_id} → {phone}", flush=True)
            logger.error(f"Failed to send Flow template for {complaint_id} → {phone}")
        else:
            print(f"[FEEDBACK] ✅ Flow template sent for {complaint_id} → {phone}", flush=True)
    except Exception as e:
        logger.error(f"Flow template send error for {complaint_id}: {e}", exc_info=True)
        print(f"[FEEDBACK] EXCEPTION sending Flow template: {e}", flush=True)

    # Mark feedback sent in building sheet (GEBB1 / GEBB2 / GETT)
    try:
        from feedback.sheets import update_building_sheet_feedback
        update_building_sheet_feedback(complaint_id, session.get("building", ""), {
            "Feedback Status": "Sent",
            "Feedback Sent At": session["feedbackSentAt"],
            "Reminder Count": "0",
        })
        print(f"[FEEDBACK] Building sheet updated for {complaint_id}", flush=True)
    except Exception as e:
        logger.error(f"Failed to mark feedback sent in building sheet: {e}")
        print(f"[FEEDBACK] Building sheet update failed: {e}", flush=True)

    # Note: save_session_to_sheet is already triggered by set_session() → _backup_session_async()
    # No need to call it again here (was causing duplicate API calls + 429 risk)

    logger.info(f"Feedback initiated for {complaint_id} → {phone}")
    print(f"[FEEDBACK] ✅ initiate_feedback completed for {complaint_id}", flush=True)
    return {"status": "ok", "message": f"Feedback initiated for {complaint_id}"}


# ── Handle Flow Form Response ────────────────────────────────────────────────

def handle_flow_response(phone: str, response_data: dict) -> bool:
    """
    Process a WhatsApp Flow form submission (nfm_reply).
    Includes Fix 2b (flow_token validation) and Fix 2c (score validation).
    """
    phone = normalize_phone(phone)
    print(f"[ENGINE] handle_flow_response called for phone={phone}", flush=True)

    session = get_session(phone)

    if not session:
        print(f"[ENGINE] ❌ NO SESSION FOUND for {phone} — cannot process feedback", flush=True)
        logger.warning(f"Flow response received from {phone} but no active session found — ignoring")
        _send_wa(phone, "This feedback session has expired or was already cleared. Thank you!")
        return False

    complaint_id = session.get("complaintId", "")
    print(f"[ENGINE] Session found for {phone}: complaint={complaint_id}, stage={session.get('stage')}", flush=True)

    # ── Fix 2b: Flow Token Validation ──────────────────────────────────────────
    # The flow_token sent with the WhatsApp Flow template is the complaint_id.
    # Validate that the token in the response matches the active session.
    flow_token = str(response_data.get("flow_token", "")).strip()
    if flow_token and flow_token != complaint_id:
        logger.warning(
            f"Flow token mismatch for {phone}: expected='{complaint_id}', "
            f"received='{flow_token}'. Rejecting to prevent wrong-complaint recording."
        )
        print(
            f"[ENGINE] ⚠️ FLOW TOKEN MISMATCH for {phone}: "
            f"session={complaint_id}, token={flow_token}",
            flush=True,
        )
        _send_wa(
            phone,
            f"⚠️ This feedback form is for a different complaint (#{flow_token}).\n"
            f"Your active feedback session is for complaint *#{complaint_id}*.\n"
            f"Please use the correct feedback form.",
        )
        return False
    # ───────────────────────────────────────────────────────────────────────────

    # Extract scores from Flow response
    # ── Fix 2c: Score Validation ───────────────────────────────────────────────
    # Reject invalid or missing scores instead of defaulting to 0.
    # Valid scores: 1–5. Score of 0 means the field was not filled.
    try:
        raw_q1 = response_data.get("resolution_rating")
        raw_q2 = response_data.get("facility_team_rating")
        raw_q3 = response_data.get("overall_rating")
        score_q1 = int(raw_q1) if raw_q1 is not None else 0
        score_q2 = int(raw_q2) if raw_q2 is not None else 0
        score_q3 = int(raw_q3) if raw_q3 is not None else 0
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid score data in Flow response for {complaint_id}: {e}")
        print(f"[ENGINE] Invalid scores: {e}. Keys in response: {list(response_data.keys())}", flush=True)
        _send_wa(
            phone,
            "⚠️ We received invalid rating values in your feedback form. "
            "Please try submitting the feedback form again with valid ratings (1–5).",
        )
        return False

    # Validate score ranges: must be 1–5, not 0
    invalid_scores = []
    for label, val in [("Resolution Rating", score_q1), ("Team Rating", score_q2), ("Overall Rating", score_q3)]:
        if val < 1 or val > 5:
            invalid_scores.append(f"{label}={val}")

    if invalid_scores:
        logger.warning(
            f"Score validation failed for {complaint_id}: {', '.join(invalid_scores)}. "
            f"Rejecting to prevent false escalations."
        )
        print(f"[ENGINE] ⚠️ INVALID SCORES for {complaint_id}: {invalid_scores}", flush=True)
        _send_wa(
            phone,
            f"⚠️ Some ratings in your feedback are missing or invalid ({', '.join(invalid_scores)}).\n"
            f"Please fill in all ratings (1–5 stars) and submit again.",
        )
        return False
    # ───────────────────────────────────────────────────────────────────────────

    tenant_comment = str(response_data.get("comments", "") or "").strip()
    if not tenant_comment:
        tenant_comment = "No comment"

    print(f"[ENGINE] Scores: Q1={score_q1} Q2={score_q2} Q3={score_q3} comment='{tenant_comment[:50]}'", flush=True)

    # Mark session as done
    session["stage"] = STAGE_DONE
    session["status"] = "received"
    set_session(phone, session)

    # Complete the feedback
    _complete_feedback(phone, session, score_q1, score_q2, score_q3, tenant_comment)
    print(f"[ENGINE] ✅ handle_flow_response completed for {complaint_id}", flush=True)
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
    send thank-you message IMMEDIATELY, then write to sheets.
    """
    complaint_id = session["complaintId"]
    now = _ist_now()
    print(f"[COMPLETE] Starting _complete_feedback for {complaint_id}", flush=True)

    # ── Fix 1: Duplicate Detection ────────────────────────────────────────────
    # Check if feedback was already received for this complaint.
    # If so, redirect to Feedback_Duplicates sheet and skip MASTER update.
    is_duplicate = False
    try:
        from feedback.sheets import check_feedback_already_received
        is_duplicate = check_feedback_already_received(complaint_id)
        if is_duplicate:
            print(f"[COMPLETE] ⚠️ DUPLICATE detected for {complaint_id} — redirecting to Feedback_Duplicates", flush=True)
            logger.warning(f"Duplicate feedback submission for {complaint_id} — redirecting to Feedback_Duplicates")
    except Exception as dup_err:
        logger.error(f"Duplicate check failed for {complaint_id}: {dup_err}")
    # ───────────────────────────────────────────────────────────────────────

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

    print(
        f"[COMPLETE] {complaint_id}: overall={overall_score} sentiment={sentiment} "
        f"escalate={should_escalate} reason='{escalation_reason}'",
        flush=True,
    )

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │ 4. Send Thank You IMMEDIATELY — BEFORE any sheet writes.          │
    # │    Previously this was step 6 (after sheets), so if sheets        │
    # │    blocked or failed, the client NEVER got a reply.               │
    # └─────────────────────────────────────────────────────────────────────┘
    try:
        _send_wa(phone, message_b(session["clientName"], complaint_id, True))
        print(f"[COMPLETE] ✅ Thank-you message sent to {phone}", flush=True)
    except Exception as e:
        logger.error(f"Failed to send thank-you for {complaint_id}: {e}")
        print(f"[COMPLETE] ❌ Thank-you send failed: {e}", flush=True)

    # 5. Write to sheets (can be slow — but client already has their reply)
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
        "Feedback Source": "GEI_BOT",
    }

    # ── Fix 1 (cont.): Redirect duplicate to Feedback_Duplicates sheet ────────
    if is_duplicate:
        try:
            from feedback.sheets import append_feedback_duplicate
            dup_data = {
                **feedback_data,
                "building": session.get("building", ""),
                "clientName": session.get("clientName", ""),
                "unitNo": session.get("unitNo", ""),
                "complaintNature": session.get("complaintNature", ""),
            }
            append_feedback_duplicate(
                complaint_id, dup_data,
                reason="Duplicate submission — feedback already received for this complaint",
            )
            print(f"[COMPLETE] Duplicate feedback redirected to Feedback_Duplicates for {complaint_id}", flush=True)
        except Exception as dup_write_err:
            logger.error(f"Failed to write duplicate feedback for {complaint_id}: {dup_write_err}")

        # Skip MASTER/building/escalation writes for duplicates
        logger.info(f"Skipping MASTER/building writes for duplicate feedback on {complaint_id}")
    else:
        # ── Normal (non-duplicate) flow: write to MASTER, building, and escalations ──
        try:
            from feedback.sheets import (
                update_building_sheet_feedback,
                update_master_feedback,
                append_escalation,
                invalidate_cache,
            )

            # 5a. Write to building sheet (GEBB1 / GEBB2 / GETT)
            update_building_sheet_feedback(
                complaint_id, session.get("building", ""), feedback_data
            )
            print(f"[COMPLETE] Building sheet updated for {complaint_id}", flush=True)

            # 5b. Write to MASTER sheet (Fix 2d: update_master_feedback preserved)
            update_master_feedback(complaint_id, feedback_data)
            print(f"[COMPLETE] MASTER sheet updated for {complaint_id}", flush=True)

            # Invalidate caches after writes so next reads see fresh data
            invalidate_cache()

            # 5c. Write escalation if needed
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
                print(f"[COMPLETE] Escalation created for {complaint_id}", flush=True)
                logger.info(f"Escalation created for {complaint_id}: {escalation_reason}")

            logger.info(f"Sheet write-back completed for {complaint_id}")

        except Exception as e:
            logger.error(f"Sheet write-back failed for {complaint_id}: {e}", exc_info=True)
            print(f"[COMPLETE] ⚠️ Sheet write-back failed (client already notified): {e}", flush=True)

    logger.info(
        f"Feedback completed for {complaint_id}: "
        f"Q1={score_q1} Q2={score_q2} Q3={score_q3} "
        f"overall={overall_score} sentiment={sentiment}"
    )

    # 6. Clean up session
    try:
        remove_session(phone)
        print(f"[COMPLETE] Session removed for {complaint_id}", flush=True)
    except Exception as e:
        logger.error(f"Failed to remove session for {complaint_id}: {e}")
        print(f"[COMPLETE] Session removal failed: {e}", flush=True)

    # 7. Check for next pending complaint
    _start_next_pending(phone)
    print(f"[COMPLETE] ✅ _complete_feedback done for {complaint_id}", flush=True)


def _start_next_pending(phone: str):
    """If there are queued complaints, start the next one immediately."""
    next_complaint = dequeue_next_complaint(phone)
    if next_complaint:
        logger.info(f"Starting next queued feedback for {phone}: {next_complaint.get('complaintId')}")
        initiate_feedback(next_complaint)

