"""
Feedback Session Store
======================
In-memory session management with Google Sheets backup.
Updated for WhatsApp Flows — simplified session structure.
"""

import logging
import threading
from datetime import datetime
from typing import Optional, Dict, List
from feedback.config import STAGE_FLOW_SENT, STAGE_DONE

logger = logging.getLogger(__name__)

_sessions = {}  # type: Dict[str, dict]
_lock = threading.Lock()
_pending_queue = {}  # type: Dict[str, List[dict]]
_queue_lock = threading.Lock()


def normalize_phone(phone: str) -> str:
    """
    Normalize phone number to format: 91XXXXXXXXXX (no +, no spaces/dashes).
    - 10-digit Indian number → prepend 91
    - Already has +91 → strip +
    - International numbers → strip + only
    """
    if not phone:
        return ""
    phone = str(phone).strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if len(phone) == 10 and phone.isdigit():
        phone = "91" + phone
    return phone


def create_session(complaint_data: dict) -> dict:
    """
    Create a new feedback session dict from complaint data.
    With WhatsApp Flows, we no longer track individual scores in the session.
    Scores arrive all at once when the Flow form is submitted.
    """
    phone = normalize_phone(complaint_data.get("clientPhone", ""))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "complaintId": complaint_data.get("complaintId", ""),
        "building": complaint_data.get("building", ""),
        "clientPhone": phone,
        "clientName": complaint_data.get("clientName", ""),
        "unitNo": complaint_data.get("unitNo", ""),
        "complaintNature": complaint_data.get("complaintNature", ""),
        "complaintDetails": complaint_data.get("complaintDetails", ""),
        "closedAt": complaint_data.get("closedAt", ""),
        "rowIndex": complaint_data.get("rowIndex", ""),
        "stage": STAGE_FLOW_SENT,
        "feedbackSentAt": now,
        "reminderCount": 0,
        "lastReminderAt": None,
        "status": "sent",
    }


def get_session(phone: str) -> Optional[dict]:
    phone = normalize_phone(phone)
    with _lock:
        return _sessions.get(phone)


def set_session(phone: str, session: dict):
    phone = normalize_phone(phone)
    with _lock:
        _sessions[phone] = session
    _backup_session_async(session)


def remove_session(phone: str):
    phone = normalize_phone(phone)
    complaint_id = None
    with _lock:
        if phone in _sessions:
            complaint_id = _sessions[phone].get("complaintId")
            del _sessions[phone]
    if complaint_id:
        _remove_from_sheet_async(complaint_id)


def get_all_active_sessions() -> list:
    with _lock:
        return [s.copy() for s in _sessions.values() if s.get("stage") != STAGE_DONE]


def has_active_session(phone: str) -> bool:
    phone = normalize_phone(phone)
    with _lock:
        session = _sessions.get(phone)
        return session is not None and session.get("stage") != STAGE_DONE


def force_clear_session(phone: str) -> bool:
    """
    Force-clear a session for a phone number (admin/debug use).
    Removes from both in-memory store and pending queue.
    Returns True if a session was found and cleared.
    """
    phone = normalize_phone(phone)
    found = False

    with _lock:
        if phone in _sessions:
            complaint_id = _sessions[phone].get("complaintId")
            del _sessions[phone]
            found = True
            if complaint_id:
                _remove_from_sheet_async(complaint_id)

    with _queue_lock:
        if phone in _pending_queue:
            _pending_queue.pop(phone, None)
            found = True

    if found:
        logger.info(f"Force-cleared session for {phone}")
    return found


def enqueue_complaint(phone: str, complaint_data: dict):
    phone = normalize_phone(phone)
    with _queue_lock:
        if phone not in _pending_queue:
            _pending_queue[phone] = []
        _pending_queue[phone].append(complaint_data)
    logger.info(f"Enqueued complaint {complaint_data.get('complaintId')} for {phone}")


def dequeue_next_complaint(phone: str) -> Optional[dict]:
    phone = normalize_phone(phone)
    with _queue_lock:
        queue = _pending_queue.get(phone, [])
        if queue:
            return queue.pop(0)
    return None


def has_pending_complaints(phone: str) -> bool:
    phone = normalize_phone(phone)
    with _queue_lock:
        return bool(_pending_queue.get(phone))


def restore_sessions_from_sheet():
    """Restore sessions from Google Sheets 'Pending Feedback' tab on startup."""
    try:
        from feedback.sheets import load_pending_sessions
        sessions = load_pending_sessions()
        with _lock:
            for s in sessions:
                phone = normalize_phone(s.get("clientPhone", ""))
                if phone and s.get("stage") != STAGE_DONE:
                    _sessions[phone] = s
        logger.info(f"Restored {len(sessions)} sessions from sheet backup")
    except Exception as e:
        logger.error(f"Failed to restore sessions from sheet: {e}", exc_info=True)


def _backup_session_async(session: dict):
    t = threading.Thread(target=_backup_session_sync, args=(session,), daemon=True)
    t.start()

def _backup_session_sync(session: dict):
    try:
        from feedback.sheets import save_session_to_sheet
        save_session_to_sheet(session)
    except Exception as e:
        logger.error(f"Sheet backup failed for {session.get('complaintId')}: {e}")

def _remove_from_sheet_async(complaint_id: str):
    t = threading.Thread(target=_remove_from_sheet_sync, args=(complaint_id,), daemon=True)
    t.start()

def _remove_from_sheet_sync(complaint_id: str):
    try:
        from feedback.sheets import remove_session_from_sheet
        remove_session_from_sheet(complaint_id)
    except Exception as e:
        logger.error(f"Sheet removal failed for {complaint_id}: {e}")
