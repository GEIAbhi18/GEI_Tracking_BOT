"""
Google Sheets Integration for Feedback Bot
==========================================
All read/write operations to Google Sheets:
  - MASTER sheet (update feedback columns)
  - Building sheets (GEBB1/GEBB2/GETT)
  - ESCALATIONS sheet (append rows)
  - Pending Feedback sheet (session backup — source of truth for reminders)

Uses gspread with service account credentials from environment variables.
"""

import logging
# pyrefly: ignore [missing-import]
import gspread
# pyrefly: ignore [missing-import]
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
import time
# pyrefly: ignore [missing-import]
import gspread.exceptions

_gc = None  # Cached gspread client
_ss = None  # Cached Spreadsheet
_worksheets = {}  # Cached Worksheets


def _retry_on_429(func, *args, **kwargs):
    """Execute a function and retry on Google Sheets API 429 quota limit error with backoff."""
    max_retries = 5
    backoff = 1.0  # start with 1 second
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            if getattr(e, "response", None) is not None and e.response.status_code == 429:
                logger.warning(f"Google Sheets API 429 rate limit exceeded. Retrying in {backoff}s... (Attempt {attempt+1}/{max_retries})")
                time.sleep(backoff)
                backoff *= 2.0  # exponential backoff
            else:
                raise
    return func(*args, **kwargs)


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
    global _ss
    if _ss is None:
        def open_ss():
            return _get_client().open_by_key(FEEDBACK_SHEET_ID)
        _ss = _retry_on_429(open_ss)
    return _ss


def _get_worksheet(sheet_name: str, auto_create: bool = False):
    """Get a specific worksheet by name, caching it to avoid API calls."""
    global _worksheets
    if sheet_name in _worksheets:
        return _worksheets[sheet_name]

    def fetch_ws():
        try:
            return _get_spreadsheet().worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            if auto_create:
                logger.info(f"Worksheet '{sheet_name}' not found — creating it")
                ss = _get_spreadsheet()
                return ss.add_worksheet(title=sheet_name, rows=1000, cols=26)
            logger.error(f"Worksheet '{sheet_name}' not found in spreadsheet")
            raise

    ws = _retry_on_429(fetch_ws)
    _worksheets[sheet_name] = ws
    return ws


# ── MASTER Sheet Operations ─────────────────────────────────────────────────

def find_complaint_row(complaint_id: str, sheet_name: str = None) -> tuple:
    """
    Find the row number for a given complaint ID in the MASTER sheet.
    Returns (worksheet, row_number, header_row) or (None, None, None) if not found.
    """
    target_sheet = sheet_name or MASTER_SHEET_NAME
    try:
        ws = _get_worksheet(target_sheet)
        headers = _retry_on_429(ws.row_values, 1)
        
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
        col_values = _retry_on_429(ws.col_values, complaint_col)
        for row_idx, val in enumerate(col_values, 1):
            if val.strip().lower() == complaint_id.strip().lower():
                return ws, row_idx, headers
        
        logger.warning(f"Complaint ID '{complaint_id}' not found in {target_sheet}")
        return None, None, None
        
    except Exception as e:
        logger.error(f"Error finding complaint row: {e}", exc_info=True)
        return None, None, None


def _get_col_index(headers, col_name):
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
      - Feedback Sent At / Feedback Received At
      - Score Q1 / Score Q2 / Score Q3
      - Overall Feedback Score
      - Sentiment
      - Customer Remarks
      - Escalation Status / Escalation Reason
      - Reminder Count / Last Reminder Sent At
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
            _retry_on_429(ws.update_cells, cells_to_update)
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
            _retry_on_429(ws.update_cells, cells_to_update)
            logger.info(f"Updated {sheet_name} sheet for complaint {complaint_id}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error updating {building} sheet for {complaint_id}: {e}", exc_info=True)
        return False


def mark_feedback_sent(complaint_id: str, timestamp: str) -> bool:
    """
    Mark Feedback Status = 'Sent' and record Feedback Sent At in the MASTER sheet.
    Called when Flow template is sent to client.
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
      - Timestamp, Complaint ID, Building, Client Name / User, Unit No,
        Complaint Nature, Complaint Details, Overall Score, Sentiment,
        Customer Remarks, Escalation Reason, Escalation Status, Action Taken
    """
    try:
        ws = _get_worksheet(ESCALATIONS_SHEET_NAME, auto_create=True)
        headers = _retry_on_429(ws.row_values, 1)
        
        if not headers:
            # Create headers if sheet is empty
            headers = [
                "Timestamp", "Complaint ID", "Building", "Client Name / User",
                "Unit No", "Complaint Nature", "Complaint Details",
                "Overall Score", "Sentiment", "Customer Remarks",
                "Escalation Reason", "Escalation Status", "Action Taken"
            ]
            _retry_on_429(ws.append_row, headers)
        
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
        
        _retry_on_429(ws.append_row, row, value_input_option="USER_ENTERED")
        logger.info(f"Escalation appended for complaint {escalation_data.get('Complaint ID')}")
        return True
        
    except Exception as e:
        logger.error(f"Error appending escalation: {e}", exc_info=True)
        return False


# ── Pending Feedback Sheet Operations ────────────────────────────────────────

# Column headers for the Pending Feedback sheet
PENDING_HEADERS = [
    "Phone", "Complaint ID", "Building", "Client Name", "Unit No",
    "Complaint Nature", "Row Index", "Sent At", "Reminder Count",
    "Last Reminder At", "Status",
]


def save_session_to_sheet(session: dict) -> bool:
    """
    Save/update a feedback session to the Pending Feedback sheet.
    Used as backup for in-memory session store.
    """
    try:
        ws = _get_worksheet(PENDING_FEEDBACK_SHEET_NAME, auto_create=True)
        headers = _retry_on_429(ws.row_values, 1)
        
        if not headers:
            headers = PENDING_HEADERS
            _retry_on_429(ws.append_row, headers)
        
        phone = session.get("clientPhone", "")
        complaint_id = session.get("complaintId", "")
        
        # Check if row exists (by phone number)
        phone_col = _get_col_index(headers, "Phone")
        existing_row = None
        if phone_col:
            col_values = _retry_on_429(ws.col_values, phone_col)
            for row_idx, val in enumerate(col_values, 1):
                if val.strip() == phone.strip():
                    existing_row = row_idx
                    break
        
        row_data = [
            phone,
            complaint_id,
            session.get("building", ""),
            session.get("clientName", ""),
            str(session.get("unitNo", "")),
            session.get("complaintNature", ""),
            str(session.get("rowIndex", "")),
            session.get("feedbackSentAt", ""),
            str(session.get("reminderCount", 0)),
            session.get("lastReminderAt", "") or "",
            session.get("status", "sent"),
        ]
        
        if existing_row:
            # Update existing row
            cell_list = []
            for col_idx, value in enumerate(row_data, 1):
                if col_idx <= len(headers):
                    cell_list.append(gspread.Cell(existing_row, col_idx, value))
            _retry_on_429(ws.update_cells, cell_list)
        else:
            _retry_on_429(ws.append_row, row_data, value_input_option="USER_ENTERED")
        
        logger.info(f"Session saved to Pending Feedback sheet for {complaint_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving session to sheet: {e}", exc_info=True)
        return False


def remove_session_from_sheet(complaint_id: str) -> bool:
    """Remove a completed session from the Pending Feedback sheet."""
    try:
        ws = _get_worksheet(PENDING_FEEDBACK_SHEET_NAME, auto_create=True)
        headers = _retry_on_429(ws.row_values, 1)
        complaint_col = _get_col_index(headers, "Complaint ID")
        
        if not complaint_col:
            return False
        
        col_values = _retry_on_429(ws.col_values, complaint_col)
        for row_idx, val in enumerate(col_values, 1):
            if val.strip() == complaint_id.strip():
                _retry_on_429(ws.delete_rows, row_idx)
                logger.info(f"Removed session from Pending Feedback sheet: {complaint_id}")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error removing session from sheet: {e}", exc_info=True)
        return False


def update_pending_reminder_count(phone: str, count: int, last_reminder_at: str) -> bool:
    """Update reminder count and last reminder timestamp in Pending Feedback sheet."""
    try:
        ws = _get_worksheet(PENDING_FEEDBACK_SHEET_NAME, auto_create=True)
        headers = _retry_on_429(ws.row_values, 1)
        
        phone_col = _get_col_index(headers, "Phone")
        if not phone_col:
            return False
        
        col_values = _retry_on_429(ws.col_values, phone_col)
        target_row = None
        for row_idx, val in enumerate(col_values, 1):
            if val.strip() == phone.strip():
                target_row = row_idx
                break
        
        if not target_row:
            logger.warning(f"Phone {phone} not found in Pending Feedback sheet for reminder update")
            return False
        
        # Update Reminder Count and Last Reminder At columns
        cells_to_update = []
        
        reminder_col = _get_col_index(headers, "Reminder Count")
        if reminder_col:
            cells_to_update.append(gspread.Cell(target_row, reminder_col, str(count)))
        
        last_reminder_col = _get_col_index(headers, "Last Reminder At")
        if last_reminder_col:
            cells_to_update.append(gspread.Cell(target_row, last_reminder_col, last_reminder_at))
        
        if cells_to_update:
            _retry_on_429(ws.update_cells, cells_to_update)
            logger.info(f"Updated reminder count for {phone}: count={count}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error updating reminder count for {phone}: {e}", exc_info=True)
        return False


def load_pending_sessions() -> list:
    """
    Load all pending sessions from the Pending Feedback sheet.
    Used on startup to restore in-memory state, and by reminder cron
    as the single source of truth.
    """
    try:
        ws = _get_worksheet(PENDING_FEEDBACK_SHEET_NAME, auto_create=True)
        records = _retry_on_429(ws.get_all_records)
        
        sessions = []
        for rec in records:
            phone = str(rec.get("Phone", "") or rec.get("Client Phone", "")).strip()
            complaint_id = str(rec.get("Complaint ID", "")).strip()
            status = str(rec.get("Status", "sent")).strip().lower()
            
            if not complaint_id or status == "done":
                continue
            
            session = {
                "complaintId": complaint_id,
                "building": str(rec.get("Building", "")),
                "clientPhone": phone,
                "clientName": str(rec.get("Client Name", "")),
                "unitNo": str(rec.get("Unit No", "")),
                "complaintNature": str(rec.get("Complaint Nature", "")),
                "rowIndex": str(rec.get("Row Index", "")),
                "stage": "flow_sent",  # All pending sessions are in flow_sent stage
                "feedbackSentAt": str(rec.get("Sent At", "") or rec.get("Feedback Sent At", "")),
                "reminderCount": int(rec["Reminder Count"]) if rec.get("Reminder Count") and str(rec["Reminder Count"]).isdigit() else 0,
                "lastReminderAt": str(rec.get("Last Reminder At", "")) or None,
                "status": status or "sent",
            }
            sessions.append(session)
        
        logger.info(f"Loaded {len(sessions)} pending sessions from sheet")
        return sessions
        
    except Exception as e:
        logger.error(f"Error loading pending sessions: {e}", exc_info=True)
        return []
