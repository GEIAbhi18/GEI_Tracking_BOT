"""
Feedback Session Store
======================
In-memory session management with Google Sheets backup.
"""

import logging
import threading
from datetime import datetime
from typing import Optional
from feedback.config import STAGE_AWAITING_START, STAGE_DONE

logger = logging.getLogger(__name__)

_sessions: dict[str, dict] = {}
_lock = threading.Lock()
_pending_queue: dict[str, list] = {}
_queue_lock = threading.Lock()


def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if len(phone) == 10 and phone.isdigit():
        phone = "91" + phone
    return phone


def create_session(complaint_data: dict) -> dict:
    phone = normalize_phone(complaint_data.get("clientPhone", ""))
    now = datetime.now().isoformat()
    return {
        "complaintId": complaint_data.get("complaintId", ""),
        "building": complaint_data.get("building", ""),
        "clientPhone": phone,
        "clientName": complaint_data.get("clientName", ""),
        "unitNo": complaint_data.get("unitNo", ""),
        "complaintNature": complaint_data.get("complaintNature", ""),
        "closedAt": complaint_data.get("closedAt", ""),
        "sessionStarted": False,
        "stage": STAGE_AWAITING_START,
        "score_q1": None,
        "score_q2": None,
        "score_q3": None,
        "tenant_comment": None,
        "feedbackSentAt": now,
        "reminderCount": 0,
        "lastReminderAt": None,
        "invalidAttempts": 0,
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
