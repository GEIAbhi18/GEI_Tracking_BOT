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

from __future__ import annotations

import logging
import threading
import time

# pyrefly: ignore [missing-import]
import gspread

# pyrefly: ignore [missing-import]
import gspread.exceptions

# pyrefly: ignore [missing-import]
from google.oauth2.service_account import Credentials

from feedback.config import (
    BUILDING_SHEETS,
    ESCALATIONS_SHEET_NAME,
    FEEDBACK_SHEET_ID,
    GOOGLE_PRIVATE_KEY,
    GOOGLE_SERVICE_ACCOUNT_EMAIL,
    MASTER_SHEET_NAME,
    PENDING_FEEDBACK_SHEET_NAME,
)

logger = logging.getLogger(__name__)

# ── Google Sheets Auth ───────────────────────────────────────────────────────

_gc = None  # Cached gspread client
_ss = None  # Cached Spreadsheet
_worksheets = {}  # Cached Worksheets
_sheets_lock = threading.Lock()  # Serialise all Sheets API calls to avoid concurrent 429s


def _retry_on_429(func, *args, **kwargs):
    """Execute func with serialisation + exponential-backoff retry on HTTP 429.

    Lock is acquired only for the actual API call and released BEFORE sleeping
    on 429 backoff so other threads can make progress.
    Lock acquisition has a 30-second timeout to prevent infinite blocking.
    """
    max_retries = 5
    backoff = 2.0  # start with 2 seconds
    for attempt in range(max_retries + 1):  # +1 for the final attempt
        acquired = _sheets_lock.acquire(timeout=30)
        if not acquired:
            logger.error(
                f"Sheets lock timeout (30s) — could not acquire lock for "
                f"{getattr(func, '__name__', func)}. Another operation is blocking."
            )
            raise RuntimeError("Google Sheets lock acquisition timed out after 30s")
        try:
            result = func(*args, **kwargs)
            return result
        except gspread.exceptions.APIError as e:
            status = None
            if getattr(e, "response", None) is not None:
                status = e.response.status_code
            if status == 429 and attempt < max_retries:
                logger.warning(
                    f"Google Sheets API 429 rate limit exceeded. "
                    f"Retrying in {backoff}s... (Attempt {attempt+1}/{max_retries})"
                )
            else:
                raise
        finally:
            _sheets_lock.release()  # Always release before sleeping
        # Sleep OUTSIDE the lock so other threads can proceed
        time.sleep(backoff)
        backoff *= 2.0  # exponential backoff


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
    if sheet_name in _worksheets:
        return _worksheets[sheet_name]

    # Pre-fetch the spreadsheet so the lock inside _get_spreadsheet() is acquired and released
    # before we lock again for fetch_ws.
    _get_spreadsheet()

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

def find_complaint_row(complaint_id: str, sheet_name: str | None = None) -> tuple:
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
        
    except Exception:
        logger.exception("Error finding complaint row")
        return None, None, None


_master_records_cache = None
_master_records_cache_time = 0.0
_master_cache_lock = threading.Lock()


def get_closed_complaints_for_client(
    phone: str,
    unit_no: str = "",
    company_name: str = "",
    building: str = "",
    limit: int = 10,
) -> list:
    """
    Fetches closed complaints for a given client from the MASTER sheet.
    Matches primarily by client phone (last 10 digits), with fallback to unit_no and company.
    Returns list of dicts with complaint details in reverse chronological order.
    """
    global _master_records_cache, _master_records_cache_time
    now_t = time.time()
    records = None
    with _master_cache_lock:
        if _master_records_cache is not None and (now_t - _master_records_cache_time) < 30:
            records = _master_records_cache

    if records is None:
        try:
            ws = _get_worksheet(MASTER_SHEET_NAME)
            records = _retry_on_429(ws.get_all_records)
            with _master_cache_lock:
                _master_records_cache = records
                _master_records_cache_time = now_t
        except Exception:
            logger.exception("Error fetching MASTER sheet records for closed complaints")
            return []

    if not records:
        return []

    target_digits = "".join(c for c in str(phone or "") if c.isdigit())
    target_last10 = target_digits[-10:] if len(target_digits) >= 10 else ""
    target_unit = str(unit_no or "").strip().upper()
    target_comp = str(company_name or "").strip().lower()
    target_bldg = str(building or "").strip().upper()

    matched = []
    seen_cids = set()

    for idx, row in enumerate(records, start=2):
        if not isinstance(row, dict):
            continue

        status = str(row.get("Status") or "").strip().lower()
        if status not in ("closed", "resolved", "completed"):
            continue

        cid = str(row.get("Complaint ID") or row.get("complaint_id") or "").strip()
        if not cid or cid in seen_cids:
            continue

        # Phone matching
        row_phone_raw = str(row.get("Client Phone") or "").strip()
        row_digits = "".join(c for c in row_phone_raw if c.isdigit())
        phone_match = bool(target_last10 and len(row_digits) >= 10 and row_digits[-10:] == target_last10)

        # Unit matching
        row_unit_raw = str(row.get("Unit No") or "").strip().upper()
        unit_match = bool(
            target_unit
            and row_unit_raw
            and (
                target_unit == row_unit_raw
                or (target_unit.isdigit() and row_unit_raw.isdigit() and int(target_unit) == int(row_unit_raw))
                or (target_unit.lstrip("0") and row_unit_raw.lstrip("0") and target_unit.lstrip("0") == row_unit_raw.lstrip("0"))
            )
        )

        # Company matching
        row_client_name = str(row.get("Client Name / User") or "").strip().lower()
        row_logged_by = str(row.get("Logged By") or "").strip().lower()
        comp_match = False
        if target_comp:
            comp_match = bool(
                target_comp in row_client_name
                or target_comp in row_logged_by
                or row_client_name in target_comp
            )

        # Building matching
        row_bldg = str(row.get("Building") or "").strip().upper()
        bldg_match = True
        if target_bldg and row_bldg:
            bldg_match = bool(target_bldg in row_bldg or row_bldg in target_bldg)

        # Ownership validation:
        # Must match phone, or unit alongside company/building
        is_owner = bool(phone_match or (unit_match and (comp_match or bldg_match)))

        if not is_owner:
            continue

        seen_cids.add(cid)
        matched.append({
            "complaintId": cid,
            "clientPhone": row_phone_raw or phone,
            "clientName": str(row.get("Client Name / User") or "").strip(),
            "unitNo": row_unit_raw or unit_no,
            "complaintNature": str(row.get("Complaint Nature") or "General").strip(),
            "complaintDetails": str(row.get("Complaint Details") or row.get("Sub Nature") or "").strip(),
            "closedAt": str(row.get("Closed At") or row.get("Updated At") or "").strip(),
            "building": row_bldg or building,
            "feedbackStatus": str(row.get("Feedback Status") or "").strip(),
            "rowIndex": idx,
        })

    logger.info(f"Found {len(matched)} closed complaints in MASTER sheet for phone={phone}, unit={unit_no}")
    return matched[:limit]



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
                cell_val = value if isinstance(value, (int, float)) else (str(value) if value is not None else "")
                cells_to_update.append(gspread.Cell(row, col_idx, cell_val))
            else:
                logger.warning(f"Column '{col_name}' not found in MASTER headers")
        
        if cells_to_update:
            _retry_on_429(ws.update_cells, cells_to_update, value_input_option="USER_ENTERED")
            logger.info(f"Updated MASTER sheet for complaint {complaint_id}: {len(cells_to_update)} columns")
            return True
        
        return False
        
    except Exception:
        logger.exception(f"Error updating MASTER feedback for {complaint_id}")
        return False


def update_building_sheet_feedback(complaint_id: str, building: str, feedback_data: dict) -> bool:
    """
    Update feedback columns in the building-specific sheet (GEBB1/GEBB2/GETT).
    Same logic as update_master_feedback but targets the building sheet.
    """
    
    # --- FIX SWAPPED ARGUMENTS (Safeguard for lingering bad sessions) ---
    c_id_raw = str(complaint_id)
    bld_raw = str(building)
    if c_id_raw.isdigit() and len(c_id_raw) >= 10 and ('-' in bld_raw):
        logger.debug(f"update_building_sheet_feedback: auto-correcting swapped arguments. complaint_id={c_id_raw}, building={bld_raw}")
        complaint_id = bld_raw
        prefix = complaint_id.split('-')[0].upper()
        if prefix == 'B1':
            building = 'GEBB1'
        elif prefix == 'B2':
            building = 'GEBB2'
        elif prefix in ('TT', 'T1'):
            building = 'GETT'
        else:
            building = bld_raw
    # --------------------------------------------------------------------

    sheet_name = BUILDING_SHEETS.get(building)
    
    if not sheet_name:
        # Fallback: Infer building from complaint_id prefix if the building parameter is invalid
        prefix = str(complaint_id).split('-')[0].upper()
        if prefix == 'B1':
            sheet_name = BUILDING_SHEETS.get('GEBB1')
        elif prefix == 'B2':
            sheet_name = BUILDING_SHEETS.get('GEBB2')
        elif prefix in ('TT', 'T1'):
            sheet_name = BUILDING_SHEETS.get('GETT')
            
    if not sheet_name:
        logger.warning(f"No sheet mapping for building '{building}' and complaint_id '{complaint_id}'")
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
                cell_val = value if isinstance(value, (int, float)) else (str(value) if value is not None else "")
                cells_to_update.append(gspread.Cell(row, col_idx, cell_val))
        
        if cells_to_update:
            _retry_on_429(ws.update_cells, cells_to_update, value_input_option="USER_ENTERED")
            logger.info(f"Updated {sheet_name} sheet for complaint {complaint_id}")
            return True
        
        return False
        
    except Exception:
        logger.exception(f"Error updating {building} sheet for {complaint_id}")
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
                    cell_val = value if isinstance(value, (int, float)) else (str(value) if value is not None else "")
                    row.append(cell_val)
                    matched = True
                    break
            if not matched:
                row.append("")
        
        _retry_on_429(ws.append_row, row, value_input_option="USER_ENTERED")
        logger.info(f"Escalation appended for complaint {escalation_data.get('Complaint ID')}")
        return True
        
    except Exception:
        logger.exception("Error appending escalation")
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
        
    except Exception:
        logger.exception("Error saving session to sheet")
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
        
    except Exception:
        logger.exception("Error removing session from sheet")
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
            cells_to_update.append(gspread.Cell(target_row, reminder_col, count if isinstance(count, (int, float)) else str(count)))
        
        last_reminder_col = _get_col_index(headers, "Last Reminder At")
        if last_reminder_col:
            cells_to_update.append(gspread.Cell(target_row, last_reminder_col, last_reminder_at))
        
        if cells_to_update:
            _retry_on_429(ws.update_cells, cells_to_update, value_input_option="USER_ENTERED")
            logger.info(f"Updated reminder count for {phone}: count={count}")
        
        return True
        
    except Exception:
        logger.exception(f"Error updating reminder count for {phone}")
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
            
            building = str(rec.get("Building", ""))

            # --- Fix swapped fields in stale Pending Feedback rows ---
            if complaint_id.isdigit() and len(complaint_id) >= 10 and ('-' in building):
                real_complaint = building
                prefix = real_complaint.split('-')[0].upper()
                if prefix == 'B1':
                    real_building = 'GEBB1'
                elif prefix == 'B2':
                    real_building = 'GEBB2'
                elif prefix in ('TT', 'T1'):
                    real_building = 'GETT'
                else:
                    real_building = building

                logger.info(
                    f"Auto-correcting swapped fields in pending session: "
                    f"phone={complaint_id}, complaintId={real_complaint}, building={real_building}"
                )
                phone = complaint_id if not phone else phone
                complaint_id = real_complaint
                building = real_building
            # --------------------------------------------------------

            session = {
                "complaintId": complaint_id,
                "building": building,
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
        
    except Exception:
        logger.exception("Error loading pending sessions")
        return []
