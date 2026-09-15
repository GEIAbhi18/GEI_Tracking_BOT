import logging
from datetime import datetime
from db import supabase
from clients.sheets_client import fetch_master_tenant_records
from clients.normalizer import normalize_client_row

logger = logging.getLogger(__name__)

# In-memory fallback cache in case Supabase table is in transition or offline
_IN_MEMORY_CLIENTS_CACHE = []


def run_client_master_sync() -> dict:
    """
    Performs full synchronization from the Google Sheet MASTER tab into Supabase.

    Steps:
      1. Fetch all rows from MASTER tab.
      2. Normalize fields, phone numbers, buildings, and compute deterministic sync_key.
      3. Validate records and log invalid rows.
      4. Upsert valid records into Supabase 'clients' table on_conflict='sync_key'.
      5. Soft-deactivate (is_active=False) any previously active clients missing from sheet.
      6. Return sync summary.
    """
    global _IN_MEMORY_CLIENTS_CACHE
    start_time = datetime.now()
    logger.info("=== Starting Client Master Sync (MASTER Tab) ===")

    stats = {
        "total_rows_read": 0,
        "valid_records": 0,
        "invalid_records": 0,
        "upserted": 0,
        "deactivated": 0,
        "errors": [],
    }

    try:
        raw_rows = fetch_master_tenant_records()
        stats["total_rows_read"] = len(raw_rows)
    except Exception as e:
        logger.error(f"Failed to fetch tenant records from Google Sheets: {e}", exc_info=True)
        stats["errors"].append(f"Sheets fetch error: {str(e)}")
        return stats

    valid_records = []
    seen_sync_keys = set()

    for row in raw_rows:
        row_num = row.get("_row_number", "?")
        normalized, is_valid, validation_errors = normalize_client_row(row, source_sheet="MASTER")

        if is_valid:
            valid_records.append(normalized)
            seen_sync_keys.add(normalized["sync_key"])
        else:
            stats["invalid_records"] += 1
            logger.warning(
                f"[SYNC] Skipped invalid row {row_num}: {', '.join(validation_errors)} | Raw: {row}"
            )
            stats["errors"].append(f"Row {row_num}: {', '.join(validation_errors)}")

    stats["valid_records"] = len(valid_records)

    # Update in-memory fallback cache
    _IN_MEMORY_CLIENTS_CACHE = [dict(r) for r in valid_records]

    # Attempt Supabase Upsert
    try:
        # Check if table exists
        supabase.table("clients").select("id").limit(1).execute()

        # Batch upsert valid records
        batch_size = 50
        for i in range(0, len(valid_records), batch_size):
            batch = valid_records[i : i + batch_size]
            supabase.table("clients").upsert(batch, on_conflict="sync_key").execute()
            stats["upserted"] += len(batch)

        # Deactivate clients not present in the latest sync
        active_res = supabase.table("clients").select("id, sync_key").eq("is_active", True).execute()
        active_db_clients = active_res.data or []

        stale_ids = [
            c["id"]
            for c in active_db_clients
            if c.get("sync_key") and c["sync_key"] not in seen_sync_keys
        ]

        if stale_ids:
            logger.info(f"Deactivating {len(stale_ids)} clients no longer present in sheet")
            for sid in stale_ids:
                supabase.table("clients").update({"is_active": False, "updated_at": datetime.now().isoformat()}).eq("id", sid).execute()
            stats["deactivated"] = len(stale_ids)

        logger.info(
            f"=== Client Sync Complete: {stats['upserted']} upserted, "
            f"{stats['invalid_records']} invalid, {stats['deactivated']} deactivated in "
            f"{(datetime.now() - start_time).total_seconds():.2f}s ==="
        )

    except Exception as db_err:
        logger.warning(
            f"Supabase 'clients' table update failed (may not be created yet): {db_err}. "
            f"In-memory fallback cache updated with {len(valid_records)} clients."
        )
        stats["errors"].append(f"Database upsert warning: {str(db_err)}")

    return stats


def get_cached_clients() -> list:
    """Returns in-memory fallback clients list."""
    global _IN_MEMORY_CLIENTS_CACHE
    return _IN_MEMORY_CLIENTS_CACHE
