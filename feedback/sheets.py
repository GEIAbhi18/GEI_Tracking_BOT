"""
Google Sheets Integration for Feedback Bot
==========================================
All read/write operations to Google Sheets:
  - MASTER sheet (update feedback columns)
  - Building sheets (GEBB1/GEBB2/GETT)
  - ESCALATIONS sheet (append rows)
  - Pending Feedback sheet (session backup)

Uses gspread with service account credentials from environment variables.
"""

import logging
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

from feedback.config import (
    GOOGLE_SERVICE_ACCOUNT_EMAIL,
    GOOGLE_PRIVATE_KEY,
    FEEDBACK_SHEET_ID,
    MASTER_SHEET_NAME,
    ESCALATIONS_SHEET_NAME,
    PENDING_FEEDBACK_SHEET_NAME,
    BUILDING_SHEETS,
)

logger = logging.getLogger(__name__)

# ── Google Sheets Auth ───────────────────────────────────────────────────────

_gc = None  # Cached gspread client


def _get_client() -> gspread.Client:
    """Lazily initialize and cache the gspread client using env-var credentials."""
    global _gc
    if _gc is None:
        if not GOOGLE_SERVICE_ACCOUNT_EMAIL or not GOOGLE_PRIVATE_KEY:
            raise RuntimeError(
                "Missing GOOGLE_SERVICE_ACCOUNT_EMAIL or GOOGLE_PRIVATE_KEY in env vars"
            )

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        # Build credentials dict from env vars (same structure as JSON key file)
        creds_info = {
            "type": "service_account",
            "project_id": "factech-feedback-automation",
            "private_key": GOOGLE_PRIVATE_KEY,
            "client_email": GOOGLE_SERVICE_ACCOUNT_EMAIL,
            "token_uri": "https://oauth2.googleapis.com/token",
        }

        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        _gc = gspread.authorize(creds)
        logger.info(f"Google Sheets client initialized for {GOOGLE_SERVICE_ACCOUNT_EMAIL}")
    return _gc


def _get_spreadsheet():
    """Open the feedback spreadsheet by ID."""
    return _get_client().open_by_key(FEEDBACK_SHEET_ID)


def _get_worksheet(sheet_name: str):
    """Get a specific worksheet by name."""
    try:
        return _get_spreadsheet().worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        logger.error(f"Worksheet '{sheet_name}' not found in spreadsheet")
        raise


# ── MASTER Sheet Operations ─────────────────────────────────────────────────

def find_complaint_row(complaint_id: str, sheet_name: str = None) -> tuple:
    """
    Find the row number for a given complaint ID in the MASTER sheet.
    Returns (worksheet, row_number, header_row) or (None, None, None) if not found.
    """
    target_sheet = sheet_name or MASTER_SHEET_NAME
    try:
        ws = _get_worksheet(target_sheet)
        headers = ws.row_values(1)
        
        # Find the Complaint ID column
        complaint_col = None
        for i, h in enumerate(headers, 1):
            if h.strip().lower() in ("complaint id", "complaintid", "complaint_id"):
                complaint_col = i
                break
        
        if complaint_col is None:
            logger.error(f"'Complaint ID' column not found in {target_sheet} sheet")
            return None, None, None
        
        # Find the row with this complaint ID
        col_values = ws.col_values(complaint_col)
        for row_idx, val in enumerate(col_values, 1):
            if val.strip() == complaint_id.strip():
                return ws, row_idx, headers
        
        logger.warning(f"Complaint ID '{complaint_id}' not found in {target_sheet}")
        return None, None, None
        
    except Exception as e:
        logger.error(f"Error finding complaint row: {e}", exc_info=True)
        return None, None, None


def _get_col_index(headers: list, col_name: str) -> int | None:
    """Get 1-indexed column number from header name (case-insensitive, partial match)."""
    col_name_lower = col_name.strip().lower()
    for i, h in enumerate(headers, 1):
        if h.strip().lower() == col_name_lower:
            return i
    # Partial match fallback
    for i, h in enumerate(headers, 1):
        if col_name_lower in h.strip().lower():
            return i
    return None


def update_master_feedback(complaint_id: str, feedback_data: dict) -> bool:
    """
    Update feedback columns in the MASTER sheet for a given complaint ID.
    
    feedback_data keys (column names):
      - Feedback Status
      - Feedback Received At
      - Overall Feedback Score
      - Score Q1 / Score Q2 / Score Q3
      - Sentiment
      - Tenant Comment
      - Escalation Status
      - Escalation Reason
      - Reminder Count
      - Last Reminder At
    """
    try:
        ws, row, headers = find_complaint_row(complaint_id)
        if ws is None:
            logger.error(f"Cannot update MASTER: complaint {complaint_id} not found")
            return False
        
        cells_to_update = []
        for col_name, value in feedback_data.items():
            col_idx = _get_col_index(headers, col_name)
            if col_idx:
                cells_to_update.append(gspread.Cell(row, col_idx, str(value) if value is not None else ""))
            else:
                logger.warning(f"Column '{col_name}' not found in MASTER headers")
        
        if cells_to_update:
            ws.update_cells(cells_to_update)
            logger.info(f"Updated MASTER sheet for complaint {complaint_id}: {len(cells_to_update)} columns")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error updating MASTER feedback for {complaint_id}: {e}", exc_info=True)
        return False


def update_building_sheet_feedback(complaint_id: str, building: str, feedback_data: dict) -> bool:
    """
    Update feedback columns in the building-specific sheet (GEBB1/GEBB2/GETT).
    Same logic as update_master_feedback but targets the building sheet.
    """
    sheet_name = BUILDING_SHEETS.get(building)
    if not sheet_name:
        logger.warning(f"No sheet mapping for building '{building}'")
        return False
    
    try:
        ws, row, headers = find_complaint_row(complaint_id, sheet_name=sheet_name)
        if ws is None:
            logger.warning(f"Complaint {complaint_id} not found in {sheet_name} sheet — skipping building update")
            return False
        
        cells_to_update = []
        for col_name, value in feedback_data.items():
            col_idx = _get_col_index(headers, col_name)
            if col_idx:
                cells_to_update.append(gspread.Cell(row, col_idx, str(value) if value is not None else ""))
        
        if cells_to_update:
            ws.update_cells(cells_to_update)
            logger.info(f"Updated {sheet_name} sheet for complaint {complaint_id}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error updating {building} sheet for {complaint_id}: {e}", exc_info=True)
        return False


def mark_feedback_sent(complaint_id: str, timestamp: str) -> bool:
    """
    Mark Feedback Status = 'Sent' and record Feedback Sent At in the MASTER sheet.
    Called when Message A is sent to client.
    """
    return update_master_feedback(complaint_id, {
        "Feedback Status": "Sent",
        "Feedback Sent At": timestamp,
    })


# ── ESCALATIONS Sheet Operations ────────────────────────────────────────────

def append_escalation(escalation_data: dict) -> bool:
    """
    Append a new row to the ESCALATIONS sheet.
    
    escalation_data keys:
      - Timestamp, Complaint ID, Building, Client Name, Unit No,
        Complaint Nature, Complaint Details, Overall Score, Sentiment,
        Tenant Comment, Escalation Reason, Escalation Status, Action Taken
    """
    try:
        ws = _get_worksheet(ESCALATIONS_SHEET_NAME)
        headers = ws.row_values(1)
        
        if not headers:
            # Create headers if sheet is empty
            headers = [
                "Timestamp", "Complaint ID", "Building", "Client Name",
                "Unit No", "Complaint Nature", "Complaint Details",
                "Overall Score", "Sentiment", "Tenant Comment",
                "Escalation Reason", "Escalation Status", "Action Taken"
            ]
            ws.append_row(headers)
        
        row = []
        for h in headers:
            h_lower = h.strip().lower()
            # Map header to data key (case-insensitive)
            matched = False
            for key, value in escalation_data.items():
                if key.strip().lower() == h_lower:
                    row.append(str(value) if value is not None else "")
                    matched = True
                    break
            if not matched:
                row.append("")
        
        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"Escalation appended for complaint {escalation_data.get('Complaint ID')}")
        return True
        
    except Exception as e:
        logger.error(f"Error appending escalation: {e}", exc_info=True)
        return False


# ── Pending Feedback Sheet Operations ────────────────────────────────────────

def save_session_to_sheet(session: dict) -> bool:
    """
    Save/update a feedback session to the Pending Feedback sheet.
    Used as backup for in-memory session store.
    """
    try:
        ws = _get_worksheet(PENDING_FEEDBACK_SHEET_NAME)
        headers = ws.row_values(1)
        
        if not headers:
            headers = [
                "Complaint ID", "Building", "Client Phone", "Client Name",
                "Unit No", "Complaint Nature", "Closed At", "Session Started",
                "Stage", "Score Q1", "Score Q2", "Score Q3", "Tenant Comment",
                "Feedback Sent At", "Reminder Count", "Last Reminder At",
                "Invalid Attempts", "Updated At"
            ]
            ws.append_row(headers)
        
        # Check if row exists
        complaint_col = _get_col_index(headers, "Complaint ID")
        if complaint_col:
            col_values = ws.col_values(complaint_col)
            existing_row = None
            for row_idx, val in enumerate(col_values, 1):
                if val.strip() == session.get("complaintId", "").strip():
                    existing_row = row_idx
                    break
        
        row_data = [
            session.get("complaintId", ""),
            session.get("building", ""),
            session.get("clientPhone", ""),
            session.get("clientName", ""),
            session.get("unitNo", ""),
            session.get("complaintNature", ""),
            session.get("closedAt", ""),
            str(session.get("sessionStarted", False)),
            session.get("stage", ""),
            str(session.get("score_q1", "")) if session.get("score_q1") is not None else "",
            str(session.get("score_q2", "")) if session.get("score_q2") is not None else "",
            str(session.get("score_q3", "")) if session.get("score_q3") is not None else "",
            session.get("tenant_comment", ""),
            session.get("feedbackSentAt", ""),
            str(session.get("reminderCount", 0)),
            session.get("lastReminderAt", ""),
            str(session.get("invalidAttempts", 0)),
            datetime.now().isoformat(),
        ]
        
        if existing_row:
            # Update existing row
            cell_list = []
            for col_idx, value in enumerate(row_data, 1):
                cell_list.append(gspread.Cell(existing_row, col_idx, value))
            ws.update_cells(cell_list)
        else:
            ws.append_row(row_data, value_input_option="USER_ENTERED")
        
        logger.info(f"Session saved to sheet for complaint {session.get('complaintId')}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving session to sheet: {e}", exc_info=True)
        return False


def remove_session_from_sheet(complaint_id: str) -> bool:
    """Remove a completed session from the Pending Feedback sheet."""
    try:
        ws = _get_worksheet(PENDING_FEEDBACK_SHEET_NAME)
        headers = ws.row_values(1)
        complaint_col = _get_col_index(headers, "Complaint ID")
        
        if not complaint_col:
            return False
        
        col_values = ws.col_values(complaint_col)
        for row_idx, val in enumerate(col_values, 1):
            if val.strip() == complaint_id.strip():
                ws.delete_rows(row_idx)
                logger.info(f"Removed session from sheet: {complaint_id}")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error removing session from sheet: {e}", exc_info=True)
        return False


def load_pending_sessions() -> list:
    """
    Load all pending sessions from the Pending Feedback sheet.
    Used on startup to restore in-memory state.
    """
    try:
        ws = _get_worksheet(PENDING_FEEDBACK_SHEET_NAME)
        records = ws.get_all_records()
        
        sessions = []
        for rec in records:
            session = {
                "complaintId": str(rec.get("Complaint ID", "")),
                "building": str(rec.get("Building", "")),
                "clientPhone": str(rec.get("Client Phone", "")),
                "clientName": str(rec.get("Client Name", "")),
                "unitNo": str(rec.get("Unit No", "")),
                "complaintNature": str(rec.get("Complaint Nature", "")),
                "closedAt": str(rec.get("Closed At", "")),
                "sessionStarted": str(rec.get("Session Started", "")).lower() == "true",
                "stage": str(rec.get("Stage", "awaiting_start")),
                "score_q1": int(rec["Score Q1"]) if rec.get("Score Q1") and str(rec["Score Q1"]).isdigit() else None,
                "score_q2": int(rec["Score Q2"]) if rec.get("Score Q2") and str(rec["Score Q2"]).isdigit() else None,
                "score_q3": int(rec["Score Q3"]) if rec.get("Score Q3") and str(rec["Score Q3"]).isdigit() else None,
                "tenant_comment": str(rec.get("Tenant Comment", "")) or None,
                "feedbackSentAt": str(rec.get("Feedback Sent At", "")),
                "reminderCount": int(rec["Reminder Count"]) if rec.get("Reminder Count") and str(rec["Reminder Count"]).isdigit() else 0,
                "lastReminderAt": str(rec.get("Last Reminder At", "")),
                "invalidAttempts": int(rec["Invalid Attempts"]) if rec.get("Invalid Attempts") and str(rec["Invalid Attempts"]).isdigit() else 0,
            }
            if session["complaintId"] and session["stage"] != "done":
                sessions.append(session)
        
        logger.info(f"Loaded {len(sessions)} pending sessions from sheet")
        return sessions
        
    except Exception as e:
        logger.error(f"Error loading pending sessions: {e}", exc_info=True)
        return []
