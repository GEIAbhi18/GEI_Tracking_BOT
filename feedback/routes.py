"""
Feedback API Routes
===================
Flask routes for the feedback bot:
  - POST   /api/feedback/initiate       — triggered by Google Apps Script
  - GET    /api/feedback/status          — check session status (debug/admin)
  - GET    /api/feedback/sessions        — list all active sessions (admin)
  - DELETE /api/feedback/session         — force-clear a stale session (admin)
"""

import logging
from flask import Blueprint, request, jsonify

from feedback.config import FEEDBACK_API_KEY
from feedback.engine import initiate_feedback
from feedback.session_store import (
    get_session, normalize_phone, get_all_active_sessions,
    force_clear_session,
)

logger = logging.getLogger(__name__)

feedback_bp = Blueprint("feedback", __name__, url_prefix="/api/feedback")


def _verify_api_key() -> bool:
    """Verify the API key from request headers."""
    if not FEEDBACK_API_KEY:
        # No API key configured — allow all requests (dev mode)
        return True
    
    auth_header = request.headers.get("Authorization", "")
    api_key = request.headers.get("X-API-Key", "")
    
    # Support both Bearer token and X-API-Key header
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        return token == FEEDBACK_API_KEY
    
    return api_key == FEEDBACK_API_KEY


@feedback_bp.route("/initiate", methods=["POST"])
def api_initiate_feedback():
    """
    Initiate a feedback session for a closed complaint.
    
    Expected JSON payload:
    {
        "complaintId": "B1-00032",
        "clientPhone": "7982990892",
        "clientName": "Sumit Singh Rawat",
        "unitNo": "301",
        "complaintNature": "BMS",
        "complaintDetails": "BMS panel issue",
        "closedAt": "2026-05-18 09:40",
        "building": "GEBB1",
        "rowIndex": 5
    }
    """
    if not _verify_api_key():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON payload"}), 400
    
    # Validate required fields
    required = ["complaintId", "clientPhone", "clientName"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({
            "status": "error",
            "message": f"Missing required fields: {', '.join(missing)}"
        }), 400
    
    import threading
    
    # Run the Google Sheets logic in the background to prevent Gunicorn timeouts
    # due to rate limits holding up the request for over 120 seconds.
    def _run_bg(payload):
        try:
            initiate_feedback(payload)
        except Exception as e:
            logger.error(f"Error in background feedback initiation: {e}")
            
    threading.Thread(target=_run_bg, args=(data,), daemon=True).start()
    
    # Return immediately so the Apps Script doesn't time out
    return jsonify({"status": "queued", "message": "Feedback initiation queued for background processing."}), 200


@feedback_bp.route("/status", methods=["GET"])
def api_feedback_status():
    """
    Check the status of a feedback session.
    Query params: phone OR complaintId
    """
    if not _verify_api_key():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    phone = request.args.get("phone", "")
    
    if phone:
        session = get_session(phone)
        if session:
            # Sanitize — don't expose internal keys
            return jsonify({
                "status": "ok",
                "session": {
                    "complaintId": session.get("complaintId"),
                    "stage": session.get("stage"),
                    "clientName": session.get("clientName"),
                    "reminderCount": session.get("reminderCount"),
                    "feedbackSentAt": session.get("feedbackSentAt"),
                }
            })
        return jsonify({"status": "not_found", "message": "No active session"}), 404
    
    return jsonify({"status": "error", "message": "Provide ?phone= query param"}), 400


@feedback_bp.route("/sessions", methods=["GET"])
def api_active_sessions():
    """List all active feedback sessions (admin/debug)."""
    if not _verify_api_key():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    sessions = get_all_active_sessions()
    return jsonify({
        "status": "ok",
        "count": len(sessions),
        "sessions": [
            {
                "complaintId": s.get("complaintId"),
                "clientName": s.get("clientName"),
                "stage": s.get("stage"),
                "building": s.get("building"),
                "reminderCount": s.get("reminderCount"),
                "feedbackSentAt": s.get("feedbackSentAt"),
            }
            for s in sessions
        ]
    })


@feedback_bp.route("/session", methods=["DELETE"])
def api_clear_session():
    """
    Force-clear a stale feedback session.
    Query param: phone (required)
    
    Use this to unblock a phone number that has a stuck session.
    Example: DELETE /api/feedback/session?phone=917717754421
    """
    if not _verify_api_key():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    phone = request.args.get("phone", "")
    if not phone:
        return jsonify({"status": "error", "message": "Provide ?phone= query param"}), 400
    
    cleared = force_clear_session(phone)
    
    if cleared:
        logger.info(f"Admin cleared session for {phone}")
        return jsonify({
            "status": "ok",
            "message": f"Session cleared for {normalize_phone(phone)}"
        })
    
    return jsonify({
        "status": "not_found",
        "message": f"No active session for {normalize_phone(phone)}"
    }), 404
