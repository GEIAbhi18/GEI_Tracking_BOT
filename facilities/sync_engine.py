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
import threading
import time
from datetime import datetime, timezone

from db import supabase
from facilities.config import (
    BUILDING_TABS,
    get_column_map,
    get_column_index,
    FACILITIES_MAX_RETRIES,
)

logger = logging.getLogger(__name__)

# ── Notification Deduplication & Flap Protection ─────────────────────────────
_NOTIFICATION_LOCK = threading.Lock()
_RECENT_NOTIFICATIONS: dict = {}  # dedup_key -> timestamp
_REF_NOTIFICATION_TIMESTAMPS: dict = {}  # ref_no -> list of timestamps

# Cooldown for exact same notification signature (10 minutes)
NOTIFICATION_DEDUP_WINDOW_SECONDS = 600

# Flap suppression: max notifications allowed for the same ref_no within flap window (5 minutes)
FLAP_WINDOW_SECONDS = 300
MAX_NOTIFS_PER_REF_WINDOW = 3


def _reset_notification_tracker():
    """Clear in-memory deduplication tracker (useful for testing)."""
    with _NOTIFICATION_LOCK:
        _RECENT_NOTIFICATIONS.clear()
        _REF_NOTIFICATION_TIMESTAMPS.clear()


def _should_suppress_notification(ref_no: str, change_type: str, details: dict) -> bool:
    """
    Check if a notification should be suppressed due to:
    1. Exact duplicate notification sent recently (within 10 minutes)
    2. Flap suppression: task rapidly changing states (> 3 times in 5 minutes)
    """
    now = time.time()
    with _NOTIFICATION_LOCK:
        cutoff = now - max(NOTIFICATION_DEDUP_WINDOW_SECONDS, FLAP_WINDOW_SECONDS)
        expired_keys = [k for k, ts in _RECENT_NOTIFICATIONS.items() if ts < cutoff]
        for k in expired_keys:
            del _RECENT_NOTIFICATIONS[k]

        for r, ts_list in list(_REF_NOTIFICATION_TIMESTAMPS.items()):
            filtered = [ts for ts in ts_list if ts >= cutoff]
            if filtered:
                _REF_NOTIFICATION_TIMESTAMPS[r] = filtered
            else:
                del _REF_NOTIFICATION_TIMESTAMPS[r]

        if change_type == "updated" and isinstance(details, dict):
            if "fields" in details and isinstance(details["fields"], list):
                sig = tuple(sorted((f.get("field", ""), str(f.get("new_value", ""))) for f in details["fields"]))
            else:
                sig = (details.get("field", ""), str(details.get("new_value", "")))
            dedup_key = f"{ref_no}:updated:{sig}"
        else:
            dedup_key = f"{ref_no}:{change_type}"

        last_sent = _RECENT_NOTIFICATIONS.get(dedup_key)
        if last_sent and (now - last_sent) < NOTIFICATION_DEDUP_WINDOW_SECONDS:
            logger.warning(
                f"Suppressing duplicate external notification for {ref_no} ({change_type}): "
                f"identical notification sent {now - last_sent:.1f}s ago."
            )
            return True

        recent_ref_times = _REF_NOTIFICATION_TIMESTAMPS.get(ref_no, [])
        if len(recent_ref_times) >= MAX_NOTIFS_PER_REF_WINDOW:
            logger.warning(
                f"Flap suppression triggered for {ref_no}: already sent {len(recent_ref_times)} "
                f"notifications in the last {FLAP_WINDOW_SECONDS}s. Suppressing to prevent flood."
            )
            return True

        _RECENT_NOTIFICATIONS[dedup_key] = now
        if ref_no not in _REF_NOTIFICATION_TIMESTAMPS:
            _REF_NOTIFICATION_TIMESTAMPS[ref_no] = []
        _REF_NOTIFICATION_TIMESTAMPS[ref_no].append(now)

        return False



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
    seen_global_refs = set()

    for building in BUILDING_TABS:
        try:
            changes_found += _poll_building_tab(building, seen_global_refs)
        except Exception as e:
            logger.error(f"Polling failed for tab {building}: {e}", exc_info=True)

    elapsed = time.time() - start_time
    logger.info(
        f"Facilities sync: polling complete in {elapsed:.1f}s — "
        f"{changes_found} change(s) detected"
    )


# pyrefly: ignore [bad-function-definition]
def _poll_building_tab(building: str, seen_global_refs: set = None) -> int:
    """Poll a single building tab and return count of changes detected."""
    from facilities.sheets_client import _get_worksheet, _retry_on_429, _row_to_dict

    if seen_global_refs is None:
        seen_global_refs = set()

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
    sheet_ref_nos = set()

    for idx, row_values in enumerate(data_rows, start=2):
        if not row_values or not row_values[0]:
            continue  # Skip empty rows

        ref_no = row_values[0].strip()
        if not ref_no:
            continue

        if ref_no in sheet_ref_nos:
            logger.warning(
                f"Duplicate ref_no '{ref_no}' found in Sheet tab '{building}' at row {idx}. "
                f"Skipping duplicate row to prevent cache oscillation and notification storms."
            )
            continue

        if ref_no in seen_global_refs:
            logger.warning(
                f"Cross-tab duplicate ref_no '{ref_no}' found in Sheet tab '{building}' at row {idx} "
                f"(already seen in another tab). Skipping duplicate row to prevent collision."
            )
            continue

        sheet_ref_nos.add(ref_no)
        seen_global_refs.add(ref_no)
        sheet_row = _row_to_dict(row_values, building)
        sheet_row["building"] = building

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
        col_map = get_column_map(building)
        changed_fields = []
        for field in col_map.values():
            if field in ("ref_no", "delay_days", "actual_completion_date"):
                continue  # ref_no is immutable; delay_days and actual_completion_date are computed by Sheets

            sheet_val = (sheet_row.get(field) or "").strip()
            cached_val = (cached.get(field) or "").strip()

            if sheet_val != cached_val:
                changed_fields.append({
                    "field": field,
                    "old_value": cached_val,
                    "new_value": sheet_val,
                })

        if not changed_fields:
            continue

        if len(changed_fields) == 1:
            cf = changed_fields[0]
            _handle_field_change(ref_no, building, cf["field"], cf["old_value"], cf["new_value"])
            changes += 1
        else:
            _handle_multi_field_change(ref_no, building, changed_fields)
            changes += len(changed_fields)

    # Check for rows in row_cache that were deleted externally from the Sheet
    try:
        cache_res = supabase.table("row_cache").select("ref_no").eq("building", building).execute()
        cached_refs = {r["ref_no"] for r in (cache_res.data or []) if r.get("ref_no")}
        deleted_refs = cached_refs - sheet_ref_nos

        for del_ref in deleted_refs:
            # Skip if recently created by GEI_BOT
            if _was_recently_synced_by_bot(del_ref, "_create_row", window_seconds=300):
                logger.info(f"Skipping deletion for {del_ref}: recently created by GEI_BOT")
                continue

            # Skip if pending creation in sync_queue
            try:
                pending_create = supabase.table("sync_queue").select("id").eq("ref_no", del_ref).eq("field", "_create_row").eq("status", "pending").execute()
                if pending_create.data:
                    logger.info(f"Skipping deletion for {del_ref}: creation pending in sync_queue")
                    continue
            except Exception as e:
                logger.warning(f"Error checking pending create for {del_ref}: {e}")

            _handle_deleted_external_row(del_ref, building)
            changes += 1
    except Exception as e:
        logger.error(f"Failed to check deleted rows for {building}: {e}")

    return changes


# pyrefly: ignore [bad-function-definition]
def _was_recently_synced_by_bot(ref_no: str, field: str = None, window_seconds: int = 300) -> bool:
    """Check if GEI_BOT recently created or updated this task/field."""
    try:
        query = supabase.table("sync_queue").select("id, field, attempted_value, synced_at, created_at").eq("ref_no", ref_no).eq("status", "synced")
        if field:
            query = query.in_("field", [field, "_create_row"])
        res = query.order("created_at", desc=True).limit(5).execute()
        if not res.data:
            return False

        for entry in res.data:
            synced_at = entry.get("synced_at") or entry.get("created_at")
            if synced_at:
                try:
                    sync_time = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
                    diff = (datetime.now(timezone.utc) - sync_time).total_seconds()
                    if diff < window_seconds:
                        return True
                except Exception:
                    pass
        return False
    except Exception as e:
        logger.error(f"Error checking recent bot sync for {ref_no}: {e}")
        return False


def _handle_new_external_row(ref_no: str, row_data: dict, building: str):
    """Handle a row that exists on the Sheet but not in our cache."""
    logger.info(f"New external row detected: {ref_no}")

    # Insert into row_cache via helper
    from facilities.sheets_client import _upsert_row_cache
    _upsert_row_cache(row_data)

    # If created recently by GEI_BOT, suppress external edit notification
    if _was_recently_synced_by_bot(ref_no, "_create_row"):
        logger.info(f"Skipping external notification for {ref_no}: created by GEI_BOT")
        return

    # Log to audit
    _log_audit_entry(
        # pyrefly: ignore [bad-argument-type]
        ref_no, "google_sheets", None,
        "Task created externally on Google Sheets",
        # pyrefly: ignore [bad-argument-type]
        None, None, str(row_data)
    )

    # Notify relevant users
    _notify_external_change(ref_no, building, "created", row_data)


def _handle_field_change(ref_no: str, building: str, field: str,
                          old_value: str, new_value: str):
    """Handle a field that changed on the Sheet since our last poll."""
    logger.info(f"External change: {ref_no}.{field}: '{old_value}' → '{new_value}'")

    # Update row_cache
    from facilities.sheets_client import _update_cache_field
    _update_cache_field(ref_no, field, new_value)

    # If updated recently by GEI_BOT, suppress external edit notification
    if _was_recently_synced_by_bot(ref_no, field):
        logger.info(f"Skipping external notification for {ref_no}.{field}: updated by GEI_BOT")
        return

    # Log to audit
    _log_audit_entry(
        # pyrefly: ignore [bad-argument-type]
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


def _handle_multi_field_change(ref_no: str, building: str, changed_fields: list):
    """Handle multiple fields that changed on the Sheet simultaneously for a single row."""
    from facilities.sheets_client import _update_cache_field

    field_names = [cf["field"] for cf in changed_fields]
    logger.info(f"External multi-field change for {ref_no}: {field_names}")

    non_bot_changes = []
    for cf in changed_fields:
        field = cf["field"]
        old_val = cf["old_value"]
        new_val = cf["new_value"]

        # Update row_cache
        _update_cache_field(ref_no, field, new_val)

        # Skip notification/audit if updated recently by GEI_BOT
        if _was_recently_synced_by_bot(ref_no, field):
            logger.info(f"Skipping external notification for {ref_no}.{field}: updated by GEI_BOT")
            continue

        _log_audit_entry(
            # pyrefly: ignore [bad-argument-type]
            ref_no, "google_sheets", None,
            f"External edit: {field} changed",
            field, old_val, new_val
        )
        non_bot_changes.append(cf)

    if not non_bot_changes:
        return

    if len(non_bot_changes) == 1:
        cf = non_bot_changes[0]
        _notify_external_change(ref_no, building, "updated", {
            "field": cf["field"],
            "old_value": cf["old_value"],
            "new_value": cf["new_value"],
        })
    else:
        _notify_external_change(ref_no, building, "updated", {
            "fields": non_bot_changes,
        })


def _handle_deleted_external_row(ref_no: str, building: str):
    """Handle a row that exists in row_cache but was deleted from the Sheet."""
    logger.info(f"External deletion detected: {ref_no} ({building}) was deleted from Google Sheet")

    # 1. Delete from row_cache
    try:
        supabase.table("row_cache").delete().eq("ref_no", ref_no).execute()
        logger.info(f"Removed deleted row {ref_no} from row_cache")
    except Exception as e:
        logger.error(f"Failed to delete {ref_no} from row_cache: {e}")

    # 2. Cancel any pending or failed sync_queue entries
    try:
        supabase.table("sync_queue").update({
            "status": "cancelled",
            "error_message": "Row was deleted externally from Google Sheet",
        }).eq("ref_no", ref_no).in_("status", ["pending", "failed"]).execute()
        logger.info(f"Cancelled sync_queue entries for deleted row {ref_no}")
    except Exception as e:
        logger.error(f"Failed to cancel sync_queue entries for {ref_no}: {e}")

    # 3. Log to audit log
    _log_audit_entry(
        # pyrefly: ignore [bad-argument-type]
        ref_no, "google_sheets", None,
        "Task deleted externally on Google Sheets"
    )

    # 4. Notify Anoop exclusively
    _notify_external_change(ref_no, building, "deleted", {})


def _notify_external_change(ref_no: str, building: str, change_type: str,
                            details: dict):
    """
    Send a WhatsApp notification to Anoop and Kanav whenever there is any change
    in any building sheet or common sheet in Facilities task tracker Google Sheet.
    """
    # 0. Suppress duplicates and rapid flapping
    if _should_suppress_notification(ref_no, change_type, details):
        return

    # 1. Notify Anoop (existing behaviour — unchanged)
    try:
        from facilities.config import resolve_anoop_phone_number
        anoop_phone = resolve_anoop_phone_number()
        if not anoop_phone:
            logger.warning(f"Could not resolve Anoop's phone number for external change on {ref_no}.")
        else:
            _send_external_edit_notification(anoop_phone, ref_no, building, change_type, details)
    except Exception as e:
        logger.error(f"Failed to notify Anoop about external change for {ref_no}: {e}")

    # 2. Notify Kanav of the same change
    try:
        from notifications.kanav_notifier import notify_kanav_task_change

        # Build a human-readable description of the change for Kanav
        if change_type == "updated" and isinstance(details, dict):
            if "fields" in details and isinstance(details["fields"], list):
                parts = []
                for f_info in details["fields"]:
                    f_name = f_info.get("field", "unknown field").replace("_", " ").title()
                    o_val = f_info.get("old_value") or "—"
                    n_val = f_info.get("new_value") or "—"
                    parts.append(f"{f_name}: '{o_val}' → '{n_val}'")
                change_desc = "; ".join(parts)
            else:
                field = details.get("field", "unknown field").replace("_", " ").title()
                old_val = details.get("old_value") or "—"
                new_val = details.get("new_value") or "—"
                change_desc = f"{field} changed from '{old_val}' to '{new_val}'"
        elif change_type == "created":
            change_desc = "New task added on Google Sheet"
        elif change_type == "deleted":
            change_desc = "Task removed from Google Sheet"
        else:
            change_desc = f"External {change_type}"

        # Fetch task title from cache if available
        task_title = ref_no
        try:
            cache_res = supabase.table("row_cache").select("issue_action").eq("ref_no", ref_no).execute()
            if cache_res.data and cache_res.data[0].get("issue_action"):
                task_title = cache_res.data[0]["issue_action"]
        except Exception:
            pass

        from facilities.config import BUILDING_NAME_MAPPING
        bldg_display = BUILDING_NAME_MAPPING.get(building, building) if building else "Sheet"
        changed_by = f"Google Sheet ({bldg_display})"

        notify_kanav_task_change(
            task_id=ref_no,
            task_title=task_title,
            change_made=change_desc,
            changed_by=changed_by,
            domain="Facilities",
        )
    except Exception as e:
        logger.error(f"Failed to notify Kanav about external change for {ref_no}: {e}")



def _send_external_edit_notification(to: str, ref_no: str, building: str,
                                     change_type: str, details: dict):
    """Send the Facilities sheet change notification exclusively to Anoop via WhatsApp."""
    try:
        from whatsapp.ux import send_text
        from facilities.config import BUILDING_NAME_MAPPING
        from datetime import timezone, timedelta

        # Current timestamp formatted in IST
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist_tz).strftime("%I:%M %p, %d %b %Y")

        bldg_name = BUILDING_NAME_MAPPING.get(building, building) if building else building
        bldg_display = f"{building} ({bldg_name})" if bldg_name and bldg_name != building else (building or "—")

        # Fetch cached task details if available
        task_desc = ""
        cached_owner = ""
        cached_status = ""
        try:
            cache_res = supabase.table("row_cache").select(
                "issue_action, owner, status, planned_date"
            ).eq("ref_no", ref_no).execute()
            if cache_res.data:
                row = cache_res.data[0]
                task_desc = row.get("issue_action") or ""
                cached_owner = row.get("owner") or ""
                cached_status = row.get("status") or ""
        except Exception:
            pass

        if change_type == "updated" and isinstance(details, dict):
            desc_line = f"*Task:* {task_desc}\n" if task_desc else ""
            if "fields" in details and isinstance(details["fields"], list):
                fields_text_lines = []
                for f_info in details["fields"]:
                    f_name = f_info.get("field", "field").replace("_", " ").title()
                    o_val = f_info.get("old_value") or "—"
                    n_val = f_info.get("new_value") or "—"
                    fields_text_lines.append(f"• *{f_name}:* {o_val} → {n_val}")
                fields_block = "\n".join(fields_text_lines)
                msg = (
                    f"📊 *Facilities Sheet Update Detected*\n\n"
                    f"*Ref:* {ref_no}\n"
                    f"*Building/Sheet:* {bldg_display}\n"
                    f"{desc_line}"
                    f"*Updates Made:*\n{fields_block}\n\n"
                    f"🕐 Detected at {now_ist} IST\n\n"
                    f"_This change was made directly on the Facilities Google Sheet._"
                )
            else:
                field = details.get("field", "unknown field")
                field_display = field.replace("_", " ").title()
                old_val = details.get("old_value") or "—"
                new_val = details.get("new_value") or "—"

                msg = (
                    f"📊 *Facilities Sheet Update Detected*\n\n"
                    f"*Ref:* {ref_no}\n"
                    f"*Building/Sheet:* {bldg_display}\n"
                    f"{desc_line}"
                    f"*Field Changed:* {field_display}\n"
                    f"*Previous:* {old_val}\n"
                    f"*Updated to:* {new_val}\n\n"
                    f"🕐 Detected at {now_ist} IST\n\n"
                    f"_This change was made directly on the Facilities Google Sheet._"
                )
        elif change_type == "created":
            issue = (details.get("issue_action") or details.get("Key Issue / Action") or task_desc or "—") if isinstance(details, dict) else "—"
            owner = (details.get("owner") or details.get("Owner") or cached_owner or "—") if isinstance(details, dict) else "—"
            status = (details.get("status") or details.get("Status") or cached_status or "—") if isinstance(details, dict) else "—"
            planned = (details.get("planned_date") or details.get("Target Date") or details.get("Planned Date") or "—") if isinstance(details, dict) else "—"

            msg = (
                f"📊 *New Task Added on Google Sheets*\n\n"
                f"*Ref:* {ref_no}\n"
                f"*Building/Sheet:* {bldg_display}\n"
                f"*Task:* {issue}\n"
                f"*Owner:* {owner}\n"
                f"*Planned Date:* {planned}\n"
                f"*Status:* {status}\n\n"
                f"🕐 Detected at {now_ist} IST\n\n"
                f"_This task was created directly on the Facilities Google Sheet._"
            )
        elif change_type == "deleted":
            desc_line = f"*Task:* {task_desc}\n" if task_desc else ""
            msg = (
                f"📊 *Task Removed from Google Sheets*\n\n"
                f"*Ref:* {ref_no}\n"
                f"*Building/Sheet:* {bldg_display}\n"
                f"{desc_line}"
                f"This row was deleted directly from the Facilities Google Sheet.\n\n"
                f"🕐 Detected at {now_ist} IST"
            )
        else:
            return

        send_text(to, msg)
        logger.info(f"Facilities external change notification sent to Anoop ({to}) for {ref_no} ({change_type})")

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

        col_idx = get_column_index(building)[field]
        _retry_on_429(ws.update_cell, row_idx, col_idx, value)

        # Mark synced
        supabase.table("sync_queue").update({
            "status": "synced",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", sync_id).execute()

        # Update cache
        _update_cache_field(ref_no, field, value)

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
        owner_pos = cache_res.data[0].get("owner") if cache_res.data else None
        if not owner_pos:
            return

        from facilities.owner_resolver import get_responsible_user_whatsapp
        from whatsapp.ux import send_text

        msg = (
            f"✅ *Sync Update — {ref_no}*\n\n"
            f"*Google Sheets:* ✅ Synced\n"
            f"The {field} update to *\"{value}\"* has been successfully "
            f"synced to Google Sheets after a previous failure.\n\n"
            f"_No action needed._"
        )

        recipient = get_responsible_user_whatsapp(owner_pos)
        if recipient and recipient.get("whatsapp_number"):
            send_text(recipient["whatsapp_number"], msg)
            logger.info(f"Retry success notification sent to {recipient['user_name']} ({recipient['whatsapp_number']}) for {ref_no}")
        else:
            user_res = supabase.table("users").select("whatsapp_number").eq("name", owner_pos).execute()
            if user_res.data:
                for user in user_res.data:
                    wa = user.get("whatsapp_number")
                    if wa:
                        send_text(wa, msg)
                        logger.info(f"Retry success notification sent to {wa} for {ref_no}")

    except Exception as e:
        logger.error(f"Failed to send retry success notification for {ref_no}: {e}")


# ── Audit Helper ─────────────────────────────────────────────────────────────

def _log_audit_entry(ref_no: str, source: str, actor: str, action: str,
                      # pyrefly: ignore [bad-function-definition]
                      field: str = None, old_value: str = None,
                      # pyrefly: ignore [bad-function-definition]
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
