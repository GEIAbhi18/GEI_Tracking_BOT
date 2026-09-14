from __future__ import annotations
import time
import threading
from whatsapp.ux import clean_phone_number

_lock = threading.Lock()
_elara_sessions: dict[str, dict] = {}
SESSION_TTL_SECONDS = 900  # 15 minutes


def get_elara_session(whatsapp_number: str) -> dict | None:
    """Retrieve active session for an Elara user, checking TTL."""
    clean_num = clean_phone_number(whatsapp_number)
    with _lock:
        session = _elara_sessions.get(clean_num)
        if not session:
            return None
        if time.time() - session.get("timestamp", 0) > SESSION_TTL_SECONDS:
            _elara_sessions.pop(clean_num, None)
            return None
        return session.copy()


def set_elara_session(whatsapp_number: str, flow_state: str, draft: dict = None, context: dict = None):
    """Set or update session for an Elara user."""
    clean_num = clean_phone_number(whatsapp_number)
    with _lock:
        current = _elara_sessions.get(clean_num, {})
        new_draft = draft if draft is not None else current.get("draft", {})
        new_context = context if context is not None else current.get("context", {})

        _elara_sessions[clean_num] = {
            "whatsapp_number": clean_num,
            "flow_state": flow_state,
            "draft": new_draft,
            "context": new_context,
            "timestamp": time.time(),
        }


def update_elara_session_draft(whatsapp_number: str, **kwargs):
    """Helper to update fields within the session's draft dict."""
    clean_num = clean_phone_number(whatsapp_number)
    with _lock:
        session = _elara_sessions.get(clean_num)
        if session:
            draft = session.setdefault("draft", {})
            draft.update(kwargs)
            session["timestamp"] = time.time()


def update_elara_session_context(whatsapp_number: str, **kwargs):
    """Helper to update fields within the session's context dict."""
    clean_num = clean_phone_number(whatsapp_number)
    with _lock:
        session = _elara_sessions.get(clean_num)
        if session:
            context = session.setdefault("context", {})
            context.update(kwargs)
            session["timestamp"] = time.time()


def clear_elara_session(whatsapp_number: str):
    """Clear the active Elara session."""
    clean_num = clean_phone_number(whatsapp_number)
    with _lock:
        _elara_sessions.pop(clean_num, None)
