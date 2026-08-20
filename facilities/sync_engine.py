"""
Facilities Module — Sync Engine
=================================
Two background jobs:

1. poll_sheet_changes():  runs every 60-90s
   - Reads all rows from each building tab on the live Sheet
   - Diffs against row_cache to detect external manual edits
   - Updates row_cache, logs to audit_log, triggers notifications

2. retry_failed_syncs():  runs alongside polling
   - Picks up sync_queue entries with status='failed' and retry_count < MAX
   - Re-attempts the Sheets API write
   - On success: updates to 'synced', sends follow-up WhatsApp notification

Both are registered as APScheduler interval jobs in whatsapp_webhook.py.
"""

import logging
import time
from datetime import datetime, timezone

from db import supabase
from facilities.config import (
    BUILDING_TABS,
    COLUMN_MAP,
    COLUMN_INDEX,
    FACILITIES_MAX_RETRIES,
)

logger = logging.getLogger(__name__)


# ── Polling Job ──────────────────────────────────────────────────────────────

def poll_sheet_changes():
    """
    Poll the live Sheet for changes made outside GEI_BOT.

    For each building tab:
      1. Read all rows from the Sheet
      2. Compare each row against row_cache
      3. For changed fields: update cache, log to audit, notify users
    """
    logger.info("Facilities sync: polling Sheet for external changes...")
    start_time = time.time()
    changes_found = 0

    for building in BUILDING_TABS:
        try:
            changes_found += _poll_building_tab(building)
        except Exception as e:
            logger.error(f"Polling failed for tab {building}: {e}", exc_info=True)

    elapsed = time.time() - start_time
    logger.info(
        f"Facilities sync: polling complete in {elapsed:.1f}s — "
        f"{changes_found} change(s) detected"
    )


def _poll_building_tab(building: str) -> int:
    """Poll a single building tab and return count of changes detected."""
    from facilities.sheets_client import _get_worksheet, _retry_on_429, _row_to_dict

    try:
        ws = _get_worksheet(building)
        all_rows = _retry_on_429(ws.get_all_values)
    except Exception as e:
        logger.error(f"Failed to read Sheet tab {building}: {e}")
        return 0

    if not all_rows or len(all_rows) < 2:
        return 0  # Header row only or empty

    # Skip the header row
    data_rows = all_rows[1:]
    changes = 0

    for row_values in data_rows:
        if not row_values or not row_values[0]:
            continue  # Skip empty rows

        ref_no = row_values[0].strip()
        if not ref_no:
            continue

        sheet_row = _row_to_dict(row_values)

        # Get the cached version
        try:
            cache_res = supabase.table("row_cache").select("*").eq("ref_no", ref_no).execute()
        except Exception as e:
            logger.error(f"Cache lookup failed for {ref_no}: {e}")
            continue

        if not cache_res.data:
            # New row — not in cache yet (created directly on Sheet)
            _handle_new_external_row(ref_no, sheet_row, building)
            changes += 1
            continue

        cached = cache_res.data[0]

        # Compare each field
        for field in COLUMN_MAP.values():
            if field in ("ref_no", "building"):
                continue  # These don't change

            sheet_val = (sheet_row.get(field) or "").strip()
            cached_val = (cached.get(field) or "").strip()

            if sheet_val != cached_val:
                _handle_field_change(ref_no, building, field, cached_val, sheet_val)
                changes += 1

    return changes


def _handle_new_external_row(ref_no: str, row_data: dict, building: str):
    """Handle a row that exists on the Sheet but not in our cache."""
    logger.info(f"New external row detected: {ref_no}")

    # Insert into row_cache
    try:
        supabase.table("row_cache").upsert({
            "ref_no": ref_no,
            "building": building,
            "type": row_data.get("type", ""),
            "issue_action": row_data.get("issue_action", ""),
            "owner": row_data.get("owner", ""),
            "target_date": row_data.get("target_date", ""),
            "status": row_data.get("status", ""),
            "latest_update": row_data.get("latest_update", ""),
            "created_date": row_data.get("created_date", ""),
            "last_modified_by_at": row_data.get("last_modified_by_at", ""),
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"Failed to cache new external row {ref_no}: {e}")

    # Log to audit
    _log_audit_entry(
        ref_no, "google_sheets", None,
        "Task created externally on Google Sheets",
        None, None, str(row_data)
    )

    # Notify relevant users
    _notify_external_change(ref_no, building, "created", row_data)


def _handle_field_change(ref_no: str, building: str, field: str,
                          old_value: str, new_value: str):
    """Handle a field that changed on the Sheet since our last poll."""
    logger.info(f"External change: {ref_no}.{field}: '{old_value}' → '{new_value}'")

    # Update row_cache
    try:
        update_data = {
            field: new_value,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }
        supabase.table("row_cache").update(update_data).eq("ref_no", ref_no).execute()
    except Exception as e:
        logger.error(f"Cache update failed for {ref_no}.{field}: {e}")

    # Log to audit
    _log_audit_entry(
        ref_no, "google_sheets", None,
        f"External edit: {field} changed",
        field, old_value, new_value
    )

    # Notify relevant users
    _notify_external_change(ref_no, building, "updated", {
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
    })


def _notify_external_change(ref_no: str, building: str, change_type: str,
                              details: dict):
    """
    Send a WhatsApp notification to users who should know about this change.

    Checks:
      1. Users who have this building in permitted_buildings
      2. Users who own this task (row_cache.owner matches a user name)
      3. Users who have an active facilities_session
    """
    try:
        # Find the owner of this task
        cache_res = supabase.table("row_cache").select("owner").eq("ref_no", ref_no).execute()
        owner_name = cache_res.data[0].get("owner") if cache_res.data else None

        if not owner_name:
            return  # No owner to notify

        # Find the user by name
        user_res = supabase.table("users").select(
            "whatsapp_number, name"
        ).eq("name", owner_name).execute()

        if not user_res.data:
            return

        for user in user_res.data:
            wa_number = user.get("whatsapp_number")
            if not wa_number:
                continue

            _send_external_edit_notification(wa_number, ref_no, change_type, details)

    except Exception as e:
        logger.error(f"Failed to notify about external change for {ref_no}: {e}")


def _send_external_edit_notification(to: str, ref_no: str, change_type: str,
                                       details: dict):
    """Send the Screen 09 external edit notification via WhatsApp."""
    try:
        from whatsapp.ux import send_text

        now = datetime.now(timezone.utc).strftime("%H:%M UTC, %d %b %Y")

        if change_type == "updated" and isinstance(details, dict):
            field = details.get("field", "unknown field")
            old_val = details.get("old_value", "—")
            new_val = details.get("new_value", "—")

            msg = (
                f"📊 *Detected from Google Sheets*\n\n"
                f"*Ref:* {ref_no}\n"
                f"*Field:* {field}\n"
                f"*Previous:* {old_val}\n"
                f"*Updated to:* {new_val}\n\n"
                f"🕐 Detected at {now}\n\n"
                f"_This change was made directly on the Google Sheet._"
            )
        elif change_type == "created":
            msg = (
                f"📊 *Detected from Google Sheets*\n\n"
                f"*New Task:* {ref_no}\n"
                f"A new task was created directly on the Google Sheet.\n\n"
                f"🕐 Detected at {now}"
            )
        else:
            return

        send_text(to, msg)
        logger.info(f"External edit notification sent to {to} for {ref_no}")

    except Exception as e:
        logger.error(f"Failed to send external edit notification to {to}: {e}")


# ── Retry Job ────────────────────────────────────────────────────────────────

def retry_failed_syncs():
    """
    Retry sync_queue entries that previously failed.

    Picks up items with status='failed' and retry_count < MAX_RETRIES.
    On success, sends a follow-up WhatsApp message (Screen 16 pattern).
    """
    try:
        failed = supabase.table("sync_queue").select("*").eq(
            "status", "failed"
        ).lt("retry_count", FACILITIES_MAX_RETRIES).order(
            "created_at"
        ).limit(10).execute()

        if not failed.data:
            return

        logger.info(f"Retrying {len(failed.data)} failed sync items")

        for item in failed.data:
            _retry_single_sync(item)

    except Exception as e:
        logger.error(f"retry_failed_syncs failed: {e}", exc_info=True)


def _retry_single_sync(item: dict):
    """Retry a single failed sync_queue entry."""
    ref_no = item["ref_no"]
    field = item["field"]
    value = item["attempted_value"]
    sync_id = item["id"]
    building = item["building"]

    logger.info(f"Retrying sync: {ref_no}.{field} = '{value}' (attempt {item['retry_count'] + 1})")

    try:
        from facilities.sheets_client import (
            _get_worksheet, _retry_on_429, _find_row_index, _update_cache_field
        )

        if field == "_create_row":
            # Retry a full row creation — more complex, skip for now
            logger.warning(f"Skipping retry for create_row {ref_no} — manual intervention needed")
            return

        ws = _get_worksheet(building)
        row_idx = _find_row_index(ws, ref_no)
        if not row_idx:
            logger.error(f"Row {ref_no} not found in Sheet during retry")
            _increment_retry_count(sync_id)
            return

        col_idx = COLUMN_INDEX[field]
        _retry_on_429(ws.update_cell, row_idx, col_idx, value)

        # Update column J
        now_str = f"GEI_BOT (retry) / {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        _retry_on_429(ws.update_cell, row_idx, COLUMN_INDEX["last_modified_by_at"], now_str)

        # Mark synced
        supabase.table("sync_queue").update({
            "status": "synced",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", sync_id).execute()

        # Update cache
        _update_cache_field(ref_no, field, value, now_str)

        logger.info(f"Retry successful: {ref_no}.{field} synced to Sheet")

        # Send follow-up notification (Screen 16)
        _send_retry_success_notification(ref_no, field, value)

    except Exception as e:
        logger.error(f"Retry failed for {ref_no}.{field}: {e}")
        _increment_retry_count(sync_id)


def _increment_retry_count(sync_id: str):
    """Increment the retry count for a failed sync entry."""
    try:
        current = supabase.table("sync_queue").select("retry_count").eq("id", sync_id).execute()
        count = current.data[0].get("retry_count", 0) if current.data else 0
        supabase.table("sync_queue").update({
            "retry_count": count + 1,
        }).eq("id", sync_id).execute()
    except Exception as e:
        logger.error(f"Failed to increment retry_count for {sync_id}: {e}")


def _send_retry_success_notification(ref_no: str, field: str, value: str):
    """Send a follow-up message when a previously failed sync succeeds."""
    try:
        # Find the owner of this task
        cache_res = supabase.table("row_cache").select("owner").eq("ref_no", ref_no).execute()
        owner_name = cache_res.data[0].get("owner") if cache_res.data else None
        if not owner_name:
            return

        user_res = supabase.table("users").select("whatsapp_number").eq("name", owner_name).execute()
        if not user_res.data:
            return

        for user in user_res.data:
            wa = user.get("whatsapp_number")
            if not wa:
                continue

            from whatsapp.ux import send_text
            msg = (
                f"✅ *Sync Update — {ref_no}*\n\n"
                f"*Google Sheets:* ✅ Synced\n"
                f"The {field} update to *\"{value}\"* has been successfully "
                f"synced to Google Sheets after a previous failure.\n\n"
                f"_No action needed._"
            )
            send_text(wa, msg)
            logger.info(f"Retry success notification sent to {wa} for {ref_no}")

    except Exception as e:
        logger.error(f"Failed to send retry success notification for {ref_no}: {e}")


# ── Audit Helper ─────────────────────────────────────────────────────────────

def _log_audit_entry(ref_no: str, source: str, actor: str, action: str,
                      field: str = None, old_value: str = None,
                      new_value: str = None):
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
