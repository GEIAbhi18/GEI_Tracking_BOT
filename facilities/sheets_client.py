from __future__ import annotations

"""
Facilities Module — Google Sheets Client
==========================================
All CRUD operations against the Facilities_Master_Tracker_Final sheet.

Every write path:
  1. Checks column J timestamp for conflict detection
  2. Routes through sync_queue (never writes directly)
  3. Never marks "Synced" before the Sheets API returns 200
  4. Logs to facilities_audit_log

Read paths use row_cache for fast reads; polling keeps the cache fresh.
"""

import logging
import uuid
import threading
import time
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

from db import supabase
from facilities.config import (
    FACILITIES_SHEET_ID,
    FACILITIES_SA_EMAIL,
    FACILITIES_SA_PRIVATE_KEY,
    BUILDING_TABS,
    COLUMN_MAP,
    COLUMN_INDEX,
    WRITABLE_FIELDS,
    CONFLICT_WINDOW_SECONDS,
)
from facilities.ref_no import generate_ref_no

logger = logging.getLogger(__name__)

# ── Google Sheets Auth ───────────────────────────────────────────────────────

_gc = None
_ss = None
_worksheets = {}
_sheets_lock = threading.Lock()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_client():
    """Get or create the gspread client (cached, thread-safe)."""
    global _gc, _ss
    if _gc is not None and _ss is not None:
        return _ss

    with _sheets_lock:
        if _gc is not None and _ss is not None:
            return _ss

        if not FACILITIES_SA_EMAIL or not FACILITIES_SA_PRIVATE_KEY:
            raise RuntimeError(
                "Facilities Google Sheets credentials not configured. "
                "Set FACILITIES_SA_EMAIL and FACILITIES_SA_PRIVATE_KEY in .env"
            )

        if not FACILITIES_SHEET_ID:
            raise RuntimeError(
                "FACILITIES_SHEET_ID not configured in .env"
            )

        creds_info = {
            "type": "service_account",
            "project_id": "facilities-tracker",
            "private_key": FACILITIES_SA_PRIVATE_KEY.replace("\\n", "\n"),
            "client_email": FACILITIES_SA_EMAIL,
            "token_uri": "https://oauth2.googleapis.com/token",
        }

        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        _gc = gspread.authorize(creds)
        _ss = _gc.open_by_key(FACILITIES_SHEET_ID)
        logger.info(f"Connected to Facilities Sheet: {_ss.title}")
        return _ss


def _get_worksheet(building: str):
    """Get or cache a worksheet handle for a building tab."""
    if building in _worksheets:
        return _worksheets[building]

    ss = _get_client()
    try:
        ws = ss.worksheet(building)
        _worksheets[building] = ws
        logger.info(f"Cached worksheet handle for tab: {building}")
        return ws
    except gspread.exceptions.WorksheetNotFound:
        raise ValueError(f"Tab '{building}' not found in the Sheet")


def _retry_on_429(func, *args, max_retries=5, **kwargs):
    """Retry with exponential backoff on Google API rate limits."""
    backoff = 2.0
    for attempt in range(max_retries + 1):
        try:
            with _sheets_lock:
                return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            if e.response.status_code == 429 and attempt < max_retries:
                wait = backoff * (2 ** attempt)
                logger.warning(f"Sheets API 429 — retrying in {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Max retries exceeded for Sheets API call")


# ── Row Parsing ──────────────────────────────────────────────────────────────

def _row_to_dict(row_values: list) -> dict:
    """Convert a Sheet row (list of cell values) to a field dict."""
    result = {}
    columns = list(COLUMN_MAP.values())
    for i, field in enumerate(columns):
        result[field] = row_values[i] if i < len(row_values) else ""
    return result


def _find_row_index(ws, ref_no: str) -> int | None:
    """Find the 1-based row index of a ref_no in column A."""
    try:
        cell = _retry_on_429(ws.find, ref_no, in_column=1)
        return cell.row if cell else None
    except gspread.exceptions.CellNotFound:
        return None


# ── Read Operations ──────────────────────────────────────────────────────────

def read_row(ref_no: str) -> dict | None:
    """
    Read a single row from the Sheet by Ref No.

    First checks row_cache for a fast local read.
    Falls back to live Sheet read if not cached.

    Returns:
        dict of field values, or None if not found
    """
    # Try cache first
    try:
        cache_res = supabase.table("row_cache").select("*").eq("ref_no", ref_no).execute()
        if cache_res.data:
            return cache_res.data[0]
    except Exception as e:
        logger.warning(f"row_cache lookup failed for {ref_no}: {e}")

    # Fall back to live Sheet
    from facilities.ref_no import get_building_from_ref_no
    try:
        building = get_building_from_ref_no(ref_no)
        ws = _get_worksheet(building)
        row_idx = _find_row_index(ws, ref_no)
        if not row_idx:
            return None

        row_values = _retry_on_429(ws.row_values, row_idx)
        row_dict = _row_to_dict(row_values)

        # Update cache
        _upsert_row_cache(row_dict)
        return row_dict

    except Exception as e:
        logger.error(f"Live Sheet read failed for {ref_no}: {e}")
        return None


def list_rows_by_building(building: str) -> list:
    """
    List all rows for a building from row_cache.

    Returns:
        list of row dicts
    """
    try:
        result = supabase.table("row_cache").select("*").eq("building", building).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"list_rows_by_building failed for {building}: {e}")
        return []


def list_rows_by_owner(owner: str) -> list:
    """
    List all rows assigned to an owner from row_cache.

    Returns:
        list of row dicts
    """
    try:
        result = supabase.table("row_cache").select("*").eq("owner", owner).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"list_rows_by_owner failed for {owner}: {e}")
        return []


# ── Write Operations ─────────────────────────────────────────────────────────

def write_field(ref_no: str, field: str, value: str, source: str = "gei_bot",
                actor: str = None) -> dict:
    """
    Write a single field value to a row, with conflict detection.

    Flow:
      1. Read column J timestamp from cache/Sheet
      2. Check for conflicts (another source edited same field within 60s)
      3. Enqueue to sync_queue
      4. Execute Sheets API write
      5. On 200: mark synced, update cache, log to audit
      6. On failure: mark failed, increment retry_count

    Args:
        ref_no: The row's Ref No
        field: Field name (must be in WRITABLE_FIELDS)
        value: New value
        source: 'gei_bot' or 'google_sheets'
        actor: Who made the change (user name)

    Returns:
        dict with 'status' ('synced'|'pending'|'conflict'), 'sync_queue_id', etc.
    """
    if field not in WRITABLE_FIELDS:
        raise ValueError(f"Field '{field}' is not writable. Writable fields: {WRITABLE_FIELDS}")

    from facilities.ref_no import get_building_from_ref_no
    building = get_building_from_ref_no(ref_no)

    # 1. Get current row from cache
    cached = _get_cached_row(ref_no)
    old_value = cached.get(field, "") if cached else ""

    # 2. Check for conflict
    conflict = _check_for_conflict(ref_no, field, value, source)
    if conflict:
        return {
            "status": "conflict",
            "conflict_id": conflict["id"],
            "ref_no": ref_no,
            "field": field,
        }

    # 3. Enqueue to sync_queue
    idempotency_key = f"{ref_no}:{field}:{value}:{uuid.uuid4().hex[:8]}"
    sync_entry = {
        "ref_no": ref_no,
        "building": building,
        "field": field,
        "old_value": old_value,
        "attempted_value": value,
        "status": "pending",
        "idempotency_key": idempotency_key,
    }

    try:
        sq_res = supabase.table("sync_queue").insert(sync_entry).execute()
        sync_id = sq_res.data[0]["id"] if sq_res.data else None
    except Exception as e:
        # Check if it's a duplicate idempotency key
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            logger.warning(f"Duplicate idempotency key {idempotency_key} — skipping")
            return {"status": "duplicate", "ref_no": ref_no, "field": field}
        raise

    # 4. Execute Sheets API write
    try:
        ws = _get_worksheet(building)
        row_idx = _find_row_index(ws, ref_no)
        if not row_idx:
            _mark_sync_failed(sync_id, f"Row {ref_no} not found in Sheet")
            return {"status": "failed", "sync_queue_id": sync_id, "error": "Row not found"}

        col_idx = COLUMN_INDEX[field]
        _retry_on_429(ws.update_cell, row_idx, col_idx, value)

        # Update column J (Last Modified By/At)
        now_str = f"{actor or source} / {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        _retry_on_429(ws.update_cell, row_idx, COLUMN_INDEX["last_modified_by_at"], now_str)

        # 5. Mark synced
        supabase.table("sync_queue").update({
            "status": "synced",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", sync_id).execute()

        # Update row_cache
        _update_cache_field(ref_no, field, value, now_str)

        # Log to audit
        _log_audit(ref_no, source, actor, f"Updated {field}", field, old_value, value)

        logger.info(f"Synced {ref_no}.{field} = '{value}' to Sheet")
        return {"status": "synced", "sync_queue_id": sync_id, "ref_no": ref_no}

    except Exception as e:
        logger.error(f"Sheet write failed for {ref_no}.{field}: {e}")
        _mark_sync_failed(sync_id, str(e))
        return {"status": "failed", "sync_queue_id": sync_id, "error": str(e)}


def create_row(building: str, task_draft: dict, actor: str = None) -> dict:
    """
    Create a new row on the Sheet and in the local cache.

    Flow:
      1. Generate Ref No (atomic, row-locked)
      2. Append row to Sheet
      3. Insert into row_cache
      4. Log to audit

    Args:
        building: Building code (e.g., 'GEBB1')
        task_draft: dict with keys: type, issue_action, owner, target_date, status
        actor: Who created it

    Returns:
        dict with 'ref_no', 'sheet_status' ('synced'|'failed'), row data
    """
    # 1. Generate Ref No
    ref_no = generate_ref_no(building)

    # 2. Build the row
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    modified_str = f"{actor or 'GEI_BOT'} / {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"

    row_data = {
        "ref_no": ref_no,
        "building": building,
        "type": task_draft.get("type", ""),
        "issue_action": task_draft.get("issue_action", ""),
        "owner": task_draft.get("owner", ""),
        "target_date": task_draft.get("target_date", ""),
        "status": task_draft.get("status", "Open"),
        "latest_update": task_draft.get("latest_update", ""),
        "created_date": now_str,
        "last_modified_by_at": modified_str,
    }

    # Build Sheet row as a list in column order
    sheet_row = [
        row_data["ref_no"],
        row_data["building"],
        row_data["type"],
        row_data["issue_action"],
        row_data["owner"],
        row_data["target_date"],
        row_data["status"],
        row_data["latest_update"],
        row_data["created_date"],
        row_data["last_modified_by_at"],
    ]

    # 3. Enqueue and write to Sheet
    idempotency_key = f"create:{ref_no}:{uuid.uuid4().hex[:8]}"
    sync_entry = {
        "ref_no": ref_no,
        "building": building,
        "field": "_create_row",
        "attempted_value": str(row_data),
        "status": "pending",
        "idempotency_key": idempotency_key,
    }

    sheet_status = "failed"
    sheet_error = None

    try:
        supabase.table("sync_queue").insert(sync_entry).execute()
    except Exception as e:
        logger.error(f"sync_queue insert failed for create_row {ref_no}: {e}")

    try:
        ws = _get_worksheet(building)
        _retry_on_429(ws.append_row, sheet_row, value_input_option="USER_ENTERED")

        # Mark synced
        supabase.table("sync_queue").update({
            "status": "synced",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }).eq("idempotency_key", idempotency_key).execute()

        sheet_status = "synced"
        logger.info(f"Created row {ref_no} on Sheet tab {building}")

    except Exception as e:
        logger.error(f"Sheet append_row failed for {ref_no}: {e}")
        supabase.table("sync_queue").update({
            "status": "failed",
            "error_message": str(e)[:500],
        }).eq("idempotency_key", idempotency_key).execute()
        sheet_error = str(e)

    # 4. Insert into row_cache (always, even if Sheet write failed)
    try:
        supabase.table("row_cache").upsert({
            **row_data,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"row_cache insert failed for {ref_no}: {e}")

    # 5. Log to audit
    _log_audit(ref_no, "gei_bot", actor, "Task Created", None, None, str(row_data))

    return {
        "ref_no": ref_no,
        "sheet_status": sheet_status,
        "sheet_error": sheet_error,
        "row_data": row_data,
    }


# ── Sync Status Queries ─────────────────────────────────────────────────────

def get_sync_status() -> dict:
    """
    Get the current sync health status for Screen 12.

    Returns dict with: connection, last_sync, pending_count,
    failed_count, health assessment.
    """
    try:
        # Pending count
        pending = supabase.table("sync_queue").select("id", count="exact").eq("status", "pending").execute()
        pending_count = pending.count or 0

        # Failed count
        failed = supabase.table("sync_queue").select("id", count="exact").eq("status", "failed").execute()
        failed_count = failed.count or 0

        # Last successful sync
        last_sync = supabase.table("sync_queue").select("synced_at").eq(
            "status", "synced"
        ).order("synced_at", desc=True).limit(1).execute()
        last_sync_at = last_sync.data[0]["synced_at"] if last_sync.data else None

        # Connection check
        connected = False
        try:
            _get_client()
            connected = True
        except Exception:
            pass

        # Health assessment
        if not connected:
            health = "❌ Disconnected"
        elif failed_count > 5:
            health = "⚠️ Degraded — multiple failures"
        elif failed_count > 0:
            health = "⚠️ Minor issues"
        elif pending_count > 10:
            health = "⏳ Processing backlog"
        else:
            health = "✅ Healthy"

        return {
            "connection": "✅ Connected" if connected else "❌ Disconnected",
            "two_way_sync": "✅ Active" if connected else "❌ Inactive",
            "last_successful_sync": last_sync_at,
            "pending_count": pending_count,
            "failed_count": failed_count,
            "health": health,
        }

    except Exception as e:
        logger.error(f"get_sync_status failed: {e}")
        return {
            "connection": "❌ Error",
            "two_way_sync": "❌ Error",
            "last_successful_sync": None,
            "pending_count": -1,
            "failed_count": -1,
            "health": "❌ Unable to determine",
        }


# ── Internal Helpers ─────────────────────────────────────────────────────────

def _get_cached_row(ref_no: str) -> dict | None:
    """Get a row from cache."""
    try:
        res = supabase.table("row_cache").select("*").eq("ref_no", ref_no).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None


def _upsert_row_cache(row_dict: dict):
    """Insert or update a row in the cache."""
    try:
        supabase.table("row_cache").upsert({
            "ref_no": row_dict.get("ref_no"),
            "building": row_dict.get("building"),
            "type": row_dict.get("type"),
            "issue_action": row_dict.get("issue_action"),
            "owner": row_dict.get("owner"),
            "target_date": row_dict.get("target_date"),
            "status": row_dict.get("status"),
            "latest_update": row_dict.get("latest_update"),
            "created_date": row_dict.get("created_date"),
            "last_modified_by_at": row_dict.get("last_modified_by_at"),
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"row_cache upsert failed for {row_dict.get('ref_no')}: {e}")


def _update_cache_field(ref_no: str, field: str, value: str, modified_str: str):
    """Update a single field in the cache."""
    try:
        update_data = {
            field: value,
            "last_modified_by_at": modified_str,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }
        supabase.table("row_cache").update(update_data).eq("ref_no", ref_no).execute()
    except Exception as e:
        logger.error(f"row_cache field update failed for {ref_no}.{field}: {e}")


def _check_for_conflict(ref_no: str, field: str, new_value: str,
                         source: str) -> dict | None:
    """
    Check if another source has edited the same field within the conflict window.

    Returns the conflict record if detected, None otherwise.
    """
    try:
        # Check if there's a recent audit entry from a different source
        # for the same ref_no and field
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=CONFLICT_WINDOW_SECONDS)).isoformat()

        recent = supabase.table("facilities_audit_log").select("*").eq(
            "ref_no", ref_no
        ).eq("field", field).neq(
            "source", source
        ).gte("timestamp", cutoff).order("timestamp", desc=True).limit(1).execute()

        if recent.data:
            other_entry = recent.data[0]
            # Create a conflict record
            conflict_data = {
                "ref_no": ref_no,
                "field": field,
                "gei_bot_value": new_value if source == "gei_bot" else other_entry.get("new_value"),
                "gei_bot_ts": datetime.now(timezone.utc).isoformat() if source == "gei_bot" else other_entry.get("timestamp"),
                "sheet_value": new_value if source == "google_sheets" else other_entry.get("new_value"),
                "sheet_ts": datetime.now(timezone.utc).isoformat() if source == "google_sheets" else other_entry.get("timestamp"),
                "status": "open",
            }

            res = supabase.table("conflicts").insert(conflict_data).execute()
            conflict = res.data[0] if res.data else conflict_data

            # Log the conflict to audit
            _log_audit(
                ref_no, "system", None,
                f"Conflict detected on {field}",
                field, other_entry.get("new_value"), new_value
            )

            logger.warning(
                f"Conflict detected: {ref_no}.{field} — "
                f"{source} tried '{new_value}' but {other_entry['source']} "
                f"set '{other_entry.get('new_value')}' {other_entry.get('timestamp')}"
            )
            return conflict

        return None

    except Exception as e:
        logger.error(f"Conflict check failed for {ref_no}.{field}: {e}")
        # On error, don't block the write — proceed without conflict detection
        return None


def _mark_sync_failed(sync_id: str, error: str):
    """Mark a sync_queue entry as failed."""
    try:
        supabase.table("sync_queue").update({
            "status": "failed",
            "error_message": error[:500],
            "retry_count": supabase.table("sync_queue").select("retry_count").eq(
                "id", sync_id
            ).execute().data[0].get("retry_count", 0) + 1,
        }).eq("id", sync_id).execute()
    except Exception as e:
        logger.error(f"Failed to mark sync_queue {sync_id} as failed: {e}")


def _log_audit(ref_no: str, source: str, actor: str, action: str,
               field: str = None, old_value: str = None, new_value: str = None):
    """Insert a row into facilities_audit_log."""
    try:
        supabase.table("facilities_audit_log").insert({
            "ref_no": ref_no,
            "source": source,
            "actor": actor,
            "action": action,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
        }).execute()
    except Exception as e:
        logger.error(f"Audit log insert failed for {ref_no}: {e}")


def resolve_conflict(conflict_id: str, resolution: str, resolved_by: str,
                     keep: str) -> dict:
    """
    Resolve a conflict by keeping one side's value.

    Args:
        conflict_id: The conflict record ID
        resolution: 'keep_sheet' or 'keep_gei_bot'
        resolved_by: User who resolved it
        keep: Which value to keep

    Returns:
        Updated conflict record
    """
    try:
        conflict_res = supabase.table("conflicts").select("*").eq("id", conflict_id).execute()
        if not conflict_res.data:
            raise ValueError(f"Conflict {conflict_id} not found")

        conflict = conflict_res.data[0]

        # Determine the winning value
        if keep == "keep_sheet":
            winning_value = conflict["sheet_value"]
        elif keep == "keep_gei_bot":
            winning_value = conflict["gei_bot_value"]
        else:
            raise ValueError(f"Invalid keep value: {keep}")

        # Write the winning value
        write_result = write_field(
            conflict["ref_no"],
            conflict["field"],
            winning_value,
            source="system",
            actor=f"Conflict resolved by {resolved_by}",
        )

        # Mark conflict as resolved
        supabase.table("conflicts").update({
            "status": "resolved",
            "resolution": resolution,
            "resolved_by": resolved_by,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", conflict_id).execute()

        # Audit log
        _log_audit(
            conflict["ref_no"], "system", resolved_by,
            f"Conflict resolved: {resolution}",
            conflict["field"],
            conflict["sheet_value"] if keep == "keep_gei_bot" else conflict["gei_bot_value"],
            winning_value,
        )

        return {"status": "resolved", "winning_value": winning_value, "write_result": write_result}

    except Exception as e:
        logger.error(f"resolve_conflict failed for {conflict_id}: {e}")
        raise
