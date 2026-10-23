from __future__ import annotations
import logging
import os
import json
import re
import uuid
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from clients.config import (
    FACTECH_BASE_URL,
    FACTECH_API_KEY,
    FACTECH_USERNAME,
    FACTECH_PASSWORD,
    get_site_id_for_building,
    is_chaitanya,
    is_developer_phone,
)

logger = logging.getLogger(__name__)

# Indian Standard Time (IST, UTC+5:30)
IST_TZ = timezone(timedelta(hours=5, minutes=30))


def get_now_ist() -> datetime:
    """Returns current datetime in Indian Standard Time (IST, UTC+5:30)."""
    return datetime.now(IST_TZ)


def get_now_ist_str() -> str:
    """Returns current timestamp string in Indian Standard Time (YYYY-MM-DD HH:MM:SS)."""
    return datetime.now(IST_TZ).strftime("%Y-%m-%d %H:%M:%S")


def format_to_ist(dt_input: str | datetime | None) -> str:
    """
    Normalizes and formats a date/time string or object to IST (UTC+5:30) string:
    'YYYY-MM-DD HH:MM:SS'.
    Handles ISO timestamps with Z or offset, and preserves already formatted IST strings.
    """
    if not dt_input:
        return datetime.now(IST_TZ).strftime("%Y-%m-%d %H:%M:%S")

    if isinstance(dt_input, datetime):
        if dt_input.tzinfo is None:
            dt_input = dt_input.replace(tzinfo=timezone.utc)
        return dt_input.astimezone(IST_TZ).strftime("%Y-%m-%d %H:%M:%S")

    # pyrefly: ignore[unnecessary-type-conversion]
    dt_str = str(dt_input).strip()
    if not dt_str:
        return datetime.now(IST_TZ).strftime("%Y-%m-%d %H:%M:%S")

    if "T" in dt_str or "Z" in dt_str or ("+" in dt_str and len(dt_str) > 10):
        try:
            clean_iso = dt_str.replace("Z", "+00:00")
            dt_parsed = datetime.fromisoformat(clean_iso)
            if dt_parsed.tzinfo is None:
                dt_parsed = dt_parsed.replace(tzinfo=timezone.utc)
            return dt_parsed.astimezone(IST_TZ).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            dt_parsed = datetime.strptime(dt_str, fmt)
            return dt_parsed.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue

    return dt_str

COMPLAINTS_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "client_complaints.json"
)

# In-memory fast cache so complaints logged in the current process are instantly accessible
_LOGGED_COMPLAINTS_CACHE = []


def _get_headers() -> dict:
    """Returns headers for Factech third-party API calls."""
    return {
        "Content-Type": "application/json",
        "apiKey": FACTECH_API_KEY,
        "x-api-key": FACTECH_API_KEY,
    }


def _mask_sensitive_headers(headers: dict) -> dict:
    """Returns a copy of headers with sensitive values masked for safe logging."""
    sensitive_keys = {"apikey", "x-api-key", "authorization", "token", "password", "secret"}
    masked = {}
    for k, v in headers.items():
        if k.lower() in sensitive_keys:
            masked[k] = "***MASKED***"
        else:
            masked[k] = v
    return masked


def _generate_request_id() -> str:
    """Generates a short unique request ID for log tracing."""
    return uuid.uuid4().hex[:12]


def _load_persisted_complaints() -> list:
    """Loads locally logged complaints from JSON disk storage."""
    try:
        if os.path.exists(COMPLAINTS_CACHE_FILE):
            with open(COMPLAINTS_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception as e:
        logger.warning(f"Error loading client complaints cache: {e}")
    return []


def _save_persisted_complaints(records: list):
    """Saves locally logged complaints to JSON disk storage."""
    try:
        os.makedirs(os.path.dirname(COMPLAINTS_CACHE_FILE), exist_ok=True)
        with open(COMPLAINTS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Error persisting client complaints cache: {e}")


def _save_local_complaint_record(record: dict):
    """
    Saves a complaint record to:
      1. In-memory cache
      2. Disk JSON file (data/client_complaints.json)
      3. Supabase facilities_audit_log (source="gei_bot")
    Preserves existing Closed status and specific Nature to prevent accidental regressions.
    """
    global _LOGGED_COMPLAINTS_CACHE
    cid = record.get("complaint_id") or record.get("com_no")
    if not cid:
        return

    # Normalize timestamps to IST
    if record.get("updated_at"):
        record["updated_at"] = format_to_ist(record["updated_at"])
    if record.get("created_at"):
        record["created_at"] = format_to_ist(record["created_at"])

    # 1. Update in-memory
    existing_idx = next(
        (i for i, c in enumerate(_LOGGED_COMPLAINTS_CACHE) if (c.get("complaint_id") or c.get("com_no")) == cid),
        None,
    )
    if existing_idx is not None:
        old = _LOGGED_COMPLAINTS_CACHE[existing_idx]
        if old.get("status") in ("Closed", "Resolved", "Completed") and record.get("status") == "In Progress":
            record["status"] = old["status"]
        if old.get("nature") and record.get("nature") in ("General Maintenance", "General", "Facility Maintenance", None):
            record["nature"] = old["nature"]
            if isinstance(record.get("complaint_category"), dict):
                record["complaint_category"]["name"] = old["nature"]
        _LOGGED_COMPLAINTS_CACHE[existing_idx] = record
    else:
        _LOGGED_COMPLAINTS_CACHE.insert(0, record)

    # 2. Update disk file
    disk_records = _load_persisted_complaints()
    d_idx = next(
        (i for i, c in enumerate(disk_records) if (c.get("complaint_id") or c.get("com_no")) == cid),
        None,
    )
    if d_idx is not None:
        old_disk = disk_records[d_idx]
        if old_disk.get("status") in ("Closed", "Resolved", "Completed") and record.get("status") == "In Progress":
            record["status"] = old_disk["status"]
        if old_disk.get("nature") and record.get("nature") in ("General Maintenance", "General", "Facility Maintenance", None):
            record["nature"] = old_disk["nature"]
            if isinstance(record.get("complaint_category"), dict):
                record["complaint_category"]["name"] = old_disk["nature"]
        disk_records[d_idx] = record
    else:
        disk_records.insert(0, record)
    _save_persisted_complaints(disk_records)

    # 3. Supabase facilities_audit_log
    try:
        from db import supabase
        supabase.table("facilities_audit_log").insert({
            "ref_no": cid,
            "source": "gei_bot",
            "action": "Client complaint logged (Factech sync queued)",
            "new_value": json.dumps(record),
        }).execute()
    except Exception as err:
        logger.warning(f"Could not persist complaint {cid} to facilities_audit_log: {err}")


def create_complaint(client_context: dict, complaint_data: dict) -> dict:
    """
    Creates a new complaint in Factech via:
    POST /v1/thirdparty/site/{siteId}/complaint

    client_context includes:
      - building, company_name, unit_number, admin_name, mobile_number, email, floor

    complaint_data includes:
      - nature, sub_nature, description, comments (optional)

    Returns dict:
      {"success": bool, "complaint_id": str, "message": str, "raw": dict, "fallback": bool}

    IMPORTANT: success=True is returned ONLY when Factech confirms complaint creation.
    On any API failure, timeout, or unexpected response, success=False is returned.
    """
    req_id = _generate_request_id()
    log_prefix = f"[FACTECH_COMPLAINT][request_id={req_id}]"

    # Identify whether client is a tester (Developer or Chaitanya)
    phone = str(client_context.get("mobile_number") or client_context.get("mobile") or "").strip()
    admin_name = str(client_context.get("admin_name") or "").strip()
    is_test_user = (
        is_chaitanya(phone)
        or is_chaitanya(admin_name)
        or is_developer_phone(phone)
        or is_developer_phone(admin_name)
    )

    if is_test_user:
        building = "Business Bay-II"
        site_id = "593"
        formatted_unit = "GEEBTWOTest"
        raw_unit = "GEEBTWOTest"
    else:
        building = client_context.get("building", "")
        site_id = get_site_id_for_building(building)
        raw_unit = str(client_context.get("unit_number", "")).strip()
        if raw_unit == "GEEBTWOTest":
            formatted_unit = "GEEBTWOTest"
        elif raw_unit and len(raw_unit) < 3:
            formatted_unit = raw_unit.zfill(3) if raw_unit.isdigit() else f"Unit-{raw_unit}"
        else:
            formatted_unit = raw_unit or "General"

    url = f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaint"

    # pyrefly: ignore [deprecated]
    # Factech server runs in UTC and strictly rejects any created_at date in the future (even micro-drifts)
    now_utc_buffered = (datetime.utcnow() - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")
    now_local = get_now_ist_str()

    nature = complaint_data.get("nature") or "General Maintenance"
    sub_nature = complaint_data.get("sub_nature") or "other"
    desc = complaint_data.get("description", "")

    # ── Build Factech-compliant payload ──────────────────────────────────
    # Per Factech API spec, the expected fields are:
    #   complaint_no, unit_no, category, sub_category, description, created_at
    payload = {
        "complaint_no": "",
        "unit_no": formatted_unit,
        "category": nature,
        "sub_category": sub_nature,
        "description": desc,
        "created_at": now_utc_buffered,
    }
    if complaint_data.get("reference_no"):
        payload["reference_no"] = str(complaint_data["reference_no"])

    # ── Render Logs (FACTECH COMPLAINT REQUEST) ──────────────────────────
    req_render_log = (
        f"\n========================================\n"
        f"FACTECH COMPLAINT REQUEST\n"
        f"Site ID: {site_id}\n"
        f"Building: {building}\n"
        f"Unit No: {formatted_unit}\n"
        f"Complaint Nature: {nature}\n"
        f"Sub Nature: {sub_nature}\n"
        f"Description: {desc}\n"
        f"API URL: {url}\n"
        f"Request Payload:\n{json.dumps(payload, indent=2)}\n"
        f"========================================"
    )
    logger.info(req_render_log)
    print(req_render_log, flush=True)

    logger.info(f"{log_prefix} Starting complaint API request")
    logger.info(f"{log_prefix} Method: POST")
    logger.info(f"{log_prefix} URL: {url}")
    logger.info(f"{log_prefix} Site ID: {site_id}")
    logger.info(f"{log_prefix} Building: {building}")
    logger.info(f"{log_prefix} Unit (raw): {raw_unit} -> Unit (formatted): {formatted_unit}")
    logger.info(f"{log_prefix} Category: {nature}")
    logger.info(f"{log_prefix} Sub-Category: {sub_nature}")
    logger.info(f"{log_prefix} Description: {desc}")
    logger.info(f"{log_prefix} Payload: {json.dumps(payload)}")
    logger.info(f"{log_prefix} Headers (masked): {json.dumps(_mask_sensitive_headers(_get_headers()))}")

    try:
        auth = None
        if FACTECH_USERNAME and FACTECH_PASSWORD:
            auth = (FACTECH_USERNAME, FACTECH_PASSWORD)
            logger.info(f"{log_prefix} Using Basic Auth: Yes (credentials masked)")
        else:
            logger.info(f"{log_prefix} Using Basic Auth: No")

        logger.info(f"{log_prefix} Sending request to Factech...")

        res = requests.post(url, json=payload, headers=_get_headers(), auth=auth, timeout=15)

        logger.info(f"{log_prefix} HTTP Status: {res.status_code}")
        logger.info(f"{log_prefix} Response Headers: {json.dumps(_mask_sensitive_headers(dict(res.headers)))}")

        data = {}
        try:
            data = res.json()
            logger.info(f"{log_prefix} Response Body (JSON): {json.dumps(data)}")
        except Exception:
            data = {"raw_text": res.text}
            logger.info(f"{log_prefix} Response Body (text): {res.text[:500]}")

        logger.info(f"{log_prefix} Parsed Response: {json.dumps(data)}")

        # ── Determine success ────────────────────────────────────────────
        # Success criteria:
        # 1. HTTP status must be 200 or 201
        # 2. Response must NOT have status="error"
        # 3. Response MUST contain a real complaint ID from Factech
        is_http_ok = res.status_code in (200, 201)
        is_not_error = data.get("status") != "error"
        has_success_flag = data.get("success") in (True, "true", "True") or data.get("status") == "success"

        complaint_id = (
            data.get("complaintId")
            or data.get("complaintNumber")
            or data.get("com_no")
            or data.get("id")
            or (data.get("data", {}).get("com_no") if isinstance(data.get("data"), dict) else None)
            or (data.get("data", {}).get("complaintId") if isinstance(data.get("data"), dict) else None)
            or (data.get("data", {}).get("complaint_no") if isinstance(data.get("data"), dict) else None)
            or (data.get("data", {}).get("id") if isinstance(data.get("data"), dict) else None)
        )

        logger.info(f"{log_prefix} HTTP OK: {is_http_ok}, Not Error Status: {is_not_error}, Success Flag: {has_success_flag}")
        logger.info(f"{log_prefix} Extracted Complaint ID: {complaint_id}")

        if is_http_ok and (is_not_error or has_success_flag) and complaint_id:
            # ── REAL SUCCESS: Factech confirmed complaint creation ────
            resp_render_log = (
                f"\n========================================\n"
                f"FACTECH COMPLAINT RESPONSE\n"
                f"HTTP Status: {res.status_code}\n"
                f"Response Body:\n{json.dumps(data, indent=2) if isinstance(data, (dict, list)) else res.text}\n"
                f"========================================"
            )
            logger.info(resp_render_log)
            print(resp_render_log, flush=True)

            logger.info(f"{log_prefix} Complaint Creation Result: SUCCESS")
            logger.info(f"{log_prefix} Complaint Number/ID: {complaint_id}")

            complaint_record = {
                "complaint_id": str(complaint_id),
                "com_no": str(complaint_id),
                "company": client_context.get("company_name", ""),
                "company_name": client_context.get("company_name", ""),
                "building": building,
                "unit": raw_unit,
                "unit_number": raw_unit,
                "unitNo": formatted_unit,
                "reference_unit_no": raw_unit,
                "admin_name": client_context.get("admin_name", ""),
                "mobile": client_context.get("mobile_number", ""),
                "mobile_number": client_context.get("mobile_number", ""),
                "category": nature,
                "nature": nature,
                "complaint_category": {"name": nature},
                "sub_nature": sub_nature,
                "description": desc,
                "details": desc,
                "status": "In Progress",
                "created_at": now_local,
                "updated_at": now_local,
                "fallback": False,
                "factech_response": data.get("message", "Complaint logged successfully"),
            }
            _save_local_complaint_record(complaint_record)

            return {
                "success": True,
                "complaint_id": str(complaint_id),
                "message": data.get("message", "Complaint logged successfully"),
                "fallback": False,
                "raw": data,
            }
        else:
            # ── FAILURE: Factech did NOT confirm complaint creation ───
            err_msg = data.get("message") or res.text[:200]
            err_render_log = (
                f"\n========================================\n"
                f"FACTECH COMPLAINT API ERROR\n"
                f"HTTP Status: {res.status_code}\n"
                f"Response Body:\n{json.dumps(data, indent=2) if isinstance(data, (dict, list)) else res.text}\n"
                f"Error: {err_msg}\n"
                f"========================================"
            )
            logger.error(err_render_log)
            print(err_render_log, flush=True)

            logger.error(f"{log_prefix} Complaint Creation Result: FAILED")
            logger.error(f"{log_prefix} Complaint API FAILED")
            logger.error(f"{log_prefix} HTTP Status: {res.status_code}")
            logger.error(f"{log_prefix} Response Body: {json.dumps(data)}")
            logger.error(f"{log_prefix} Error: {err_msg}")

            if not is_http_ok:
                logger.error(f"{log_prefix} Failure reason: HTTP status {res.status_code} (expected 200/201)")
            elif not is_not_error and not has_success_flag:
                logger.error(f"{log_prefix} Failure reason: API returned error status")
            elif not complaint_id:
                logger.error(f"{log_prefix} Failure reason: No complaint ID in response (complaint may not have been created)")

            return {
                "success": False,
                "complaint_id": None,
                "message": f"Factech API error: {err_msg}",
                "fallback": False,
                "raw": data,
            }

    except requests.Timeout as te:
        timeout_render_log = (
            f"\n========================================\n"
            f"FACTECH COMPLAINT API ERROR\n"
            f"HTTP Status: None\n"
            f"Response Body: None\n"
            f"Error: Request timed out after 15 seconds\n"
            f"========================================"
        )
        logger.error(timeout_render_log)
        print(timeout_render_log, flush=True)

        logger.error(f"{log_prefix} Complaint API FAILED")
        logger.error(f"{log_prefix} Error: Request timed out after 15 seconds")
        logger.error(f"{log_prefix} Complaint Creation Result: FAILED (timeout)")
        return {
            "success": False,
            "complaint_id": None,
            "message": "Factech API request timed out. Please try again.",
            "fallback": False,
            "raw": {},
        }
    except Exception as e:
        exc_render_log = (
            f"\n========================================\n"
            f"FACTECH COMPLAINT API ERROR\n"
            f"HTTP Status: None\n"
            f"Response Body: None\n"
            f"Error: {str(e)}\n"
            f"========================================"
        )
        logger.error(exc_render_log)
        print(exc_render_log, flush=True)

        logger.error(f"{log_prefix} Complaint API FAILED")
        logger.error(f"{log_prefix} Error: {e}")
        logger.error(f"{log_prefix} Complaint Creation Result: FAILED (exception)", exc_info=True)
        return {
            "success": False,
            "complaint_id": None,
            "message": f"Unable to connect to Factech: {str(e)}",
            "fallback": False,
            "raw": {},
        }


def update_complaint(
    client_context: dict,
    complaint_id: str,
    update_data: dict,
    existing_complaint: dict | None = None,
) -> dict:
    """
    Updates an existing complaint in Factech via:
    PUT /v1/thirdparty/site/{siteId}/complaint

    And updates the persistent local complaint store & Supabase facilities_audit_log.
    Preserves original complaint nature and status to prevent overwriting with defaults.
    """
    req_id = _generate_request_id()
    log_prefix = f"[FACTECH_COMPLAINT][request_id={req_id}]"

    # pyrefly: ignore [unnecessary-type-conversion]
    clean_cid = str(complaint_id).lstrip("#").strip()
    phone = str(client_context.get("mobile_number") or client_context.get("mobile") or "").strip()
    admin_name = str(client_context.get("admin_name") or "").strip()
    is_test_user = (
        is_chaitanya(phone)
        or is_chaitanya(admin_name)
        or is_developer_phone(phone)
        or is_developer_phone(admin_name)
    )

    if is_test_user:
        building = "Business Bay-II"
        site_id = "593"
    else:
        building = client_context.get("building", "")
        site_id = get_site_id_for_building(building)

    url = f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaint"

    new_desc = update_data.get("description", "").strip()
    remarks = update_data.get("remarks") or new_desc
    new_status = update_data.get("status")

    # Factech third-party PUT is a bulk event array endpoint.
    # Supported events: 'description', 'remarks', 'status' (Open|WIP|Hold|Closed|Cancel|Reopen), 'rating'.
    # pyrefly: ignore[deprecated]
    now_utc_buffered = (datetime.utcnow() - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")

    payload = [
        {
            "complaint_no": clean_cid,
            "event": "description",
            "value": new_desc,
            "updated_at": now_utc_buffered,
        }
    ]
    if remarks and remarks != new_desc:
        payload.append({
            "complaint_no": clean_cid,
            "event": "remarks",
            "value": remarks,
            "updated_at": now_utc_buffered,
        })
    if new_status and new_status in ("Open", "WIP", "Hold", "Closed", "Cancel", "Reopen"):
        payload.append({
            "complaint_no": clean_cid,
            "event": "status",
            "value": new_status,
            "updated_at": now_utc_buffered,
        })

    # ── Render Logs (FACTECH COMPLAINT UPDATE REQUEST) ───────────────────
    req_render_log = (
        f"\n========================================\n"
        f"FACTECH COMPLAINT UPDATE REQUEST\n"
        f"Site ID: {site_id}\n"
        f"Building: {building}\n"
        f"Complaint ID: {clean_cid}\n"
        f"Description: {new_desc}\n"
        f"API URL: {url}\n"
        f"Request Payload:\n{json.dumps(payload, indent=2)}\n"
        f"========================================"
    )
    logger.info(req_render_log)
    print(req_render_log, flush=True)

    logger.info(f"{log_prefix} Starting complaint UPDATE request")
    logger.info(f"{log_prefix} Method: PUT")
    logger.info(f"{log_prefix} URL: {url}")
    logger.info(f"{log_prefix} Complaint ID: {clean_cid}")
    logger.info(f"{log_prefix} Payload: {json.dumps(payload)}")
    logger.info(f"{log_prefix} Headers (masked): {json.dumps(_mask_sensitive_headers(_get_headers()))}")

    # 1. Attempt Factech PUT endpoint
    api_success = False
    api_resp_data = {}
    err_msg = ""
    try:
        auth = None
        if FACTECH_USERNAME and FACTECH_PASSWORD:
            auth = (FACTECH_USERNAME, FACTECH_PASSWORD)
        res = requests.put(url, json=payload, headers=_get_headers(), auth=auth, timeout=12)

        logger.info(f"{log_prefix} HTTP Status: {res.status_code}")

        try:
            api_resp_data = res.json()
            logger.info(f"{log_prefix} Response Body: {json.dumps(api_resp_data)}")
        except Exception:
            api_resp_data = {"text": res.text}
            logger.info(f"{log_prefix} Response Body (text): {res.text[:500]}")

        # Factech bulk PUT returns: {"status": "success", "data": [{"status": "success", ...}], "message": "bulk response"}
        # Or in error: {"status": "error", "message": "..."}
        if res.status_code in (200, 201) and api_resp_data.get("status") == "success":
            data_items = api_resp_data.get("data")
            if isinstance(data_items, list) and data_items:
                all_ok = all(item.get("status") == "success" for item in data_items if isinstance(item, dict))
                api_success = all_ok
                if not all_ok:
                    err_msg = "; ".join(item.get("message", "Item update failed") for item in data_items if isinstance(item, dict) and item.get("status") != "success")
            else:
                api_success = True
        else:
            err_msg = api_resp_data.get("message") or (res.text[:200] if hasattr(res, "text") else "Unknown error")

        if api_success:
            resp_render_log = (
                f"\n========================================\n"
                f"FACTECH COMPLAINT UPDATE RESPONSE\n"
                f"HTTP Status: {res.status_code}\n"
                f"Response Body:\n{json.dumps(api_resp_data, indent=2) if isinstance(api_resp_data, (dict, list)) else res.text}\n"
                f"========================================"
            )
            logger.info(resp_render_log)
            print(resp_render_log, flush=True)
            logger.info(f"{log_prefix} Complaint Update Result: SUCCESS")
        else:
            err_render_log = (
                f"\n========================================\n"
                f"FACTECH COMPLAINT UPDATE API ERROR\n"
                f"HTTP Status: {res.status_code}\n"
                f"Response Body:\n{json.dumps(api_resp_data, indent=2) if isinstance(api_resp_data, (dict, list)) else res.text}\n"
                f"Error: {err_msg}\n"
                f"========================================"
            )
            logger.error(err_render_log)
            print(err_render_log, flush=True)
            logger.error(f"{log_prefix} Complaint Update Result: FAILED - {err_msg}")
    except Exception as e:
        err_msg = str(e)
        logger.warning(f"{log_prefix} Factech PUT update complaint error: {e}")

    # 2. Resilient local update in cache & disk store
    now_local = get_now_ist_str()
    updated_record = None

    # Retrieve existing complaint metadata to preserve Nature, Category, Status, Created At
    orig_record = dict(existing_complaint) if existing_complaint else {}

    # Check in-memory & disk
    all_local = _LOGGED_COMPLAINTS_CACHE + _load_persisted_complaints()
    for rec in all_local:
        rcid = str(rec.get("complaint_id") or rec.get("com_no") or "").lstrip("#")
        if rcid == clean_cid:
            if not orig_record:
                orig_record = rec
            updated_record = rec
            break

    # If not found locally, query live Factech to preserve original nature & status
    if not orig_record:
        try:
            live_list = get_complaints(client_context, days_back=365, active_only=False)
            for m in live_list:
                mcid = str(m.get("complaint_id") or m.get("com_no") or m.get("id") or "").lstrip("#")
                if mcid == clean_cid:
                    orig_record = m
                    break
        except Exception as e:
            logger.debug(f"Could not retrieve live complaint record for {clean_cid}: {e}")

    orig_cat = orig_record.get("complaint_category") or {}
    orig_nature = (
        (orig_cat.get("name") if isinstance(orig_cat, dict) else None)
        or orig_record.get("nature")
        or orig_record.get("category")
        or orig_record.get("Complaint Nature")
        or client_context.get("nature")
        or "General"
    )
    orig_sub_nature = (
        orig_record.get("sub_nature")
        or orig_record.get("sub_category")
        or orig_record.get("Sub Nature")
        or "other"
    )
    orig_status = new_status or orig_record.get("status") or orig_record.get("Status") or "In Progress"
    orig_created_at = (
        orig_record.get("created_at")
        or orig_record.get("createdAt")
        or orig_record.get("Logged At")
        or now_local
    )
    orig_desc = (
        orig_record.get("description")
        or orig_record.get("details")
        or orig_record.get("Complaint Details")
        or ""
    )

    combined_desc = (
        f"{orig_desc} | Update: {new_desc}"
        if (orig_desc and new_desc and new_desc not in orig_desc)
        else (new_desc or orig_desc)
    )

    if updated_record:
        updated_record["description"] = combined_desc
        updated_record["details"] = combined_desc
        updated_record["updated_at"] = now_local
        # Ensure we don't accidentally overwrite nature or status with generic defaults
        if orig_nature and orig_nature not in ("General Maintenance", "General", "Facility Maintenance"):
            updated_record["nature"] = orig_nature
            updated_record["category"] = orig_nature
            updated_record["complaint_category"] = {"name": orig_nature}
        if orig_status:
            updated_record["status"] = orig_status
    else:
        # Create record entry preserving original nature and status!
        raw_unit = str(client_context.get("unit_number", "")).strip() or str(orig_record.get("unit", ""))
        updated_record = {
            "complaint_id": clean_cid,
            "com_no": clean_cid,
            "company": client_context.get("company_name", "") or orig_record.get("company", ""),
            "building": client_context.get("building", "") or orig_record.get("building", ""),
            "unit": raw_unit,
            "unitNo": raw_unit,
            "admin_name": client_context.get("admin_name", "") or orig_record.get("admin_name", ""),
            "mobile": client_context.get("mobile_number", "") or orig_record.get("mobile", ""),
            "mobile_number": client_context.get("mobile_number", "") or orig_record.get("mobile", ""),
            "nature": orig_nature,
            "category": orig_nature,
            "complaint_category": {"name": orig_nature},
            "sub_nature": orig_sub_nature,
            "description": combined_desc,
            "details": combined_desc,
            "status": orig_status,
            "created_at": format_to_ist(orig_created_at),
            "updated_at": now_local,
            "closed_at": orig_record.get("closed_at") or orig_record.get("Closed At"),
            "fallback": not api_success,
        }

    _save_local_complaint_record(updated_record)

    # 3. Log update action to facilities_audit_log
    try:
        from db import supabase
        supabase.table("facilities_audit_log").insert({
            "ref_no": clean_cid,
            "source": "gei_bot",
            "action": "Client complaint updated",
            "field": "description",
            "new_value": json.dumps({
                "complaint_id": clean_cid,
                "updated_description": new_desc,
                "timestamp": now_local,
                "factech_api_synced": api_success,
            }),
        }).execute()
    except Exception as err:
        logger.warning(f"Could not write complaint update to facilities_audit_log: {err}")

    if api_success:
        return {
            "success": True,
            "complaint_id": clean_cid,
            "message": "Complaint updated successfully",
            "raw": api_resp_data,
        }
    else:
        return {
            "success": False,
            "complaint_id": clean_cid,
            "message": f"Factech API error: {err_msg}" if err_msg else "Could not update complaint on Factech",
            "raw": api_resp_data,
        }


def derive_complaint_progress(complaint: dict) -> str:
    """
    Derives accurate progress information strictly from authoritative Factech fields:
    - status, staff, remarks, tat, closed_at.
    Never fabricates percentages, stages, or unsupported technician activities.
    """
    if not complaint or not isinstance(complaint, dict):
        return "Progress details unavailable"

    status = str(complaint.get("status") or "").strip()
    staff = complaint.get("staff") or []
    staff_names = []
    if isinstance(staff, list):
        for s in staff:
            if isinstance(s, dict) and s.get("name"):
                staff_names.append(str(s.get("name")).strip())
            elif isinstance(s, str) and s.strip():
                staff_names.append(s.strip())
    elif isinstance(staff, str) and staff.strip():
        staff_names.append(staff.strip())

    remarks = complaint.get("remarks")
    tat = complaint.get("tat")
    closed_at = complaint.get("closed_at")

    parts = []
    st_lower = status.lower()
    if st_lower in ("closed", "resolved", "completed"):
        if closed_at:
            parts.append(f"Resolved and closed ({format_to_ist(closed_at)})")
        else:
            parts.append("Resolved and closed")
        if tat and str(tat).strip() and str(tat).strip() != "00:00:00":
            parts.append(f"TAT: {str(tat).strip()}")
    elif st_lower == "wip":
        if staff_names:
            parts.append(f"Work in progress (Assigned to {', '.join(staff_names)})")
        else:
            parts.append("Work in progress by facilities team")
        if tat and str(tat).strip() and str(tat).strip() != "00:00:00":
            parts.append(f"TAT: {str(tat).strip()}")
    elif st_lower == "hold":
        parts.append("On hold pending parts/review")
    elif st_lower == "open":
        if staff_names:
            parts.append(f"Assigned to {', '.join(staff_names)}")
        else:
            parts.append("Logged and awaiting technician assignment")
    elif st_lower in ("cancel", "cancelled"):
        parts.append("Complaint cancelled")
    elif st_lower == "reopen":
        parts.append("Complaint reopened for further review")
    elif status:
        parts.append(f"Status: {status}")

    if remarks and str(remarks).strip() and str(remarks).strip().lower() not in ("none", "null"):
        clean_rem = str(remarks).strip()
        parts.append(f"Remarks: {clean_rem}")

    if not parts:
        return "Progress details unavailable"
    return " | ".join(parts)


def format_complaint_status_and_progress(complaint: dict) -> str:
    """
    Formats the complaint status block:
      Complaint ID: B2-00090
      Status: <Actual Factech status>
    """
    cid = str(complaint.get("com_no") or complaint.get("complaint_id") or complaint.get("id") or "").lstrip("#").strip()
    status = str(complaint.get("status") or "Open").strip()

    return (
        f"Complaint ID: {cid}\n"
        f"Status: {status}"
    )


def _finalize_factech_complaint(item: dict) -> dict:
    """Ensures timestamps and status from Factech are normalized and cached."""
    if not isinstance(item, dict):
        return item

    # Ensure timestamps are in IST
    if item.get("updated_at"):
        item["updated_at"] = format_to_ist(item["updated_at"])
    if item.get("created_at"):
        item["created_at"] = format_to_ist(item["created_at"])
    if item.get("closed_at"):
        item["closed_at"] = format_to_ist(item["closed_at"])

    # Update in-memory cache
    item_cid = str(item.get("com_no") or item.get("complaintId") or item.get("id") or "").lstrip("#").strip()
    for existing in _LOGGED_COMPLAINTS_CACHE:
        e_cid = str(existing.get("com_no") or existing.get("complaint_id") or "").lstrip("#").strip()
        if e_cid.lower() == item_cid.lower():
            existing.update(item)
            break

    return item


def get_complaint_by_id(
    site_id: str | int = "",
    complaint_id: str = "",
    client_context: dict | None = None,
    dt_hint: str | None = None,
) -> dict | None:
    """
    Retrieves a single complaint record directly from Factech API as the source of truth.

    1. If dt_hint is available (from sheets, audit log, or local store), queries a 3-day
       Factech window around that date.
    2. If not found or no dt_hint, checks recent Factech complaints across latest pages.
    3. If still not found, attempts to locate dt_hint via MASTER feedback sheet or audit log.
    4. Normalizes timestamps to IST and updates local memory/cache with the live status.
    5. Returns dict if found, None if not found in Factech.
    """
    if not complaint_id:
        return None

    # pyrefly: ignore[unnecessary-type-conversion]
    clean_cid = str(complaint_id).lstrip("#").strip()
    site_id = str(site_id).strip() if site_id is not None else ""
    if not site_id:
        if client_context:
            phone = str(client_context.get("mobile_number") or client_context.get("mobile") or "").strip()
            admin_name = str(client_context.get("admin_name") or "").strip()
            if is_chaitanya(phone) or is_chaitanya(admin_name) or is_developer_phone(phone) or is_developer_phone(admin_name):
                site_id = "593"
            else:
                site_id = get_site_id_for_building(client_context.get("building", ""))
        else:
            if clean_cid.upper().startswith("B1-"):
                site_id = "467"
            elif clean_cid.upper().startswith("B2-"):
                site_id = "593"
            elif clean_cid.upper().startswith("TT"):
                site_id = "926"
            else:
                from clients.config import DEFAULT_SITE_ID
                site_id = DEFAULT_SITE_ID

    auth = (FACTECH_USERNAME, FACTECH_PASSWORD) if FACTECH_USERNAME and FACTECH_PASSWORD else None

    # Helper function to query a Factech date range
    def _query_date_range(start_datetime: datetime, end_datetime: datetime) -> dict | None:
        from_str = quote(start_datetime.strftime("%Y-%m-%d 00:00:00"))
        to_str = quote(end_datetime.strftime("%Y-%m-%d 23:59:59"))
        url = f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaints?from={from_str}&to={to_str}&pageNo=1&perPage=50"
        try:
            res = requests.get(url, headers=_get_headers(), auth=auth, timeout=12)
            if res.status_code == 200:
                body = res.json()
                objs = body.get("objects") if isinstance(body, dict) else (body if isinstance(body, list) else [])
                for o in (objs or []):
                    o_cid = str(o.get("com_no") or o.get("complaintId") or o.get("id") or "").lstrip("#").strip()
                    if o_cid.lower() == clean_cid.lower():
                        return o
                # If there are multiple pages in this range, check remaining pages
                if isinstance(body, dict):
                    cnt = body.get("count", 0)
                    per_p = body.get("perPage") or 20
                    t_pages = (cnt + per_p - 1) // per_p
                    if t_pages > 1:
                        for p in range(2, min(t_pages + 1, 10)):
                            p_url = f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaints?from={from_str}&to={to_str}&pageNo={p}&perPage={per_p}"
                            p_res = requests.get(p_url, headers=_get_headers(), auth=auth, timeout=10)
                            if p_res.status_code == 200:
                                p_body = p_res.json()
                                for o in (p_body.get("objects") or []):
                                    o_cid = str(o.get("com_no") or o.get("complaintId") or o.get("id") or "").lstrip("#").strip()
                                    if o_cid.lower() == clean_cid.lower():
                                        return o
        except Exception as e:
            logger.debug(f"Factech query error for {clean_cid} in [{start_datetime}, {end_datetime}]: {e}")
        return None

    # Step 1: Use dt_hint if provided
    parsed_hint_dt = None
    if dt_hint:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y"):
            try:
                # pyrefly: ignore[unnecessary-type-conversion]
                parsed_hint_dt = datetime.strptime(str(dt_hint).strip()[:19], fmt)
                break
            except Exception:
                continue

    if parsed_hint_dt:
        matched = _query_date_range(parsed_hint_dt - timedelta(days=3), parsed_hint_dt + timedelta(days=3))
        if matched:
            return _finalize_factech_complaint(matched)
        return None

    # Step 2: Try to find dt_hint from sheet if no dt_hint was passed
    try:
        from feedback.sheets import find_complaint_row, _get_worksheet
        _, row_idx, headers = find_complaint_row(clean_cid, sheet_name="MASTER")
        if row_idx and headers:
            ws = _get_worksheet("MASTER")
            if ws:
                row_vals = ws.row_values(row_idx)
                for h_name, r_val in zip(headers, row_vals):
                    if h_name in ("Logged At", "Created At", "Closed At") and r_val:
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y"):
                            try:
                                parsed_hint_dt = datetime.strptime(str(r_val).strip()[:19], fmt)
                                break
                            except Exception:
                                continue
                        if parsed_hint_dt:
                            break
    except Exception as sheet_err:
        logger.debug(f"Could not retrieve sheet hint for {clean_cid}: {sheet_err}")

    if parsed_hint_dt:
        matched = _query_date_range(parsed_hint_dt - timedelta(days=3), parsed_hint_dt + timedelta(days=3))
        if matched:
            return _finalize_factech_complaint(matched)
        return None

    # Step 3: Query recent complaints in Factech (last 30 days) when no date hint exists
    now = datetime.now()
    matched = _query_date_range(now - timedelta(days=30), now)
    if matched:
        return _finalize_factech_complaint(matched)

    # Step 4: If not found in last 30 days and no date hint exists, check previous monthly chunks
    for months_back in range(1, 4):
        chunk_end = now - timedelta(days=(months_back - 1) * 30)
        chunk_start = now - timedelta(days=months_back * 30)
        matched = _query_date_range(chunk_start, chunk_end)
        if matched:
            return _finalize_factech_complaint(matched)

    return None


def get_complaints(
    client_context: dict,
    days_back: int = 180,
    page_no: int = 1,
    per_page: int = 50,
    active_only: bool = False,
) -> list:
    """
    Fetches complaints for the given client from Factech:
    GET /v1/thirdparty/site/{siteId}/complaints?from=...&to=...&pageNo=...&perPage=...

    Also retrieves GEI_BOT logged complaints from the persistent store and
    facilities_audit_log so complaints logged through GEI_BOT are immediately
    accessible without delay.

    Filters complaints strictly by client unit number, mobile number, or company.
    Returns list of complaint dicts in reverse chronological order.
    """
    phone = str(client_context.get("mobile_number") or client_context.get("mobile") or "").strip()
    admin_name = str(client_context.get("admin_name") or "").strip()
    is_test_user = (
        is_chaitanya(phone)
        or is_chaitanya(admin_name)
        or is_developer_phone(phone)
        or is_developer_phone(admin_name)
    )

    if is_test_user:
        building = "Business Bay-II"
        site_id = "593"
    else:
        building = client_context.get("building", "")
        site_id = get_site_id_for_building(building)

    now = datetime.now()
    start_dt = now - timedelta(days=days_back)
    from_str = start_dt.strftime("%Y-%m-%d 00:00:00")
    to_str = now.strftime("%Y-%m-%d 23:59:59")

    url = (
        f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaints"
        f"?from={quote(from_str)}&to={quote(to_str)}&pageNo={page_no}&perPage={per_page}"
    )

    logger.info(f"Fetching complaints from Factech: site={site_id}, days_back={days_back}, page={page_no}")

    raw_list = []
    auth = None
    if FACTECH_USERNAME and FACTECH_PASSWORD:
        auth = (FACTECH_USERNAME, FACTECH_PASSWORD)

    try:
        res = requests.get(url, headers=_get_headers(), auth=auth, timeout=15)
        logger.info(f"Factech GET response code: {res.status_code}")

        if res.status_code == 200:
            body = res.json()
            if isinstance(body, list):
                raw_list = list(body)
            elif isinstance(body, dict):
                raw_list = list(body.get("objects") or body.get("data") or body.get("complaints") or [])
                total_count = body.get("count") or len(raw_list)
                # Factech API returns records in ASCENDING order of created_at.
                # If page_no == 1 was requested and total_pages > 1, fetch the latest pages
                # so the client receives the most recent complaints rather than the oldest ones.
                if page_no == 1 and total_count > len(raw_list):
                    per_p = body.get("perPage") or 20
                    total_pages = (total_count + per_p - 1) // per_p
                    if total_pages > 1:
                        # Fetch the most recent pages (up to 3 latest pages)
                        recent_pages = [p for p in range(total_pages, max(1, total_pages - 3), -1)]
                        for rp in recent_pages:
                            if rp == 1:
                                continue
                            try:
                                p_url = (
                                    f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaints"
                                    f"?from={quote(from_str)}&to={quote(to_str)}&pageNo={rp}&perPage={per_p}"
                                )
                                p_res = requests.get(p_url, headers=_get_headers(), auth=auth, timeout=10)
                                if p_res.status_code == 200:
                                    p_body = p_res.json()
                                    p_objs = p_body.get("objects") or []
                                    raw_list.extend(p_objs)
                            except Exception as rp_err:
                                logger.debug(f"Error fetching page {rp}: {rp_err}")
    except Exception as e:
        logger.error(f"Error fetching complaints from Factech: {e}", exc_info=True)

    # Client matching parameters
    target_unit = str(client_context.get("unit_number", "")).strip().upper()
    target_mobile = str(client_context.get("mobile_number", "")).strip()
    target_mobile_digits = "".join(ch for ch in target_mobile if ch.isdigit())
    target_company = str(client_context.get("company_name", "")).strip().lower()

    # Load locally recorded complaints from memory, disk cache, and facilities_audit_log
    local_candidates = []
    # 1. In-memory
    local_candidates.extend(_LOGGED_COMPLAINTS_CACHE)
    # 2. Disk JSON file
    local_candidates.extend(_load_persisted_complaints())
    # 3. Supabase facilities_audit_log
    try:
        from db import supabase
        audit_res = (
            supabase.table("facilities_audit_log")
            .select("*")
            .eq("source", "gei_bot")
            .order("timestamp", desc=True)
            .limit(50)
            .execute()
        )
        for row in (audit_res.data or []):
            try:
                action = row.get("action") or ""
                if "complaint" in action.lower():
                    meta = json.loads(row.get("new_value") or "{}")
                    if meta.get("complaint_id") or meta.get("com_no"):
                        cid_meta = meta.get("complaint_id") or meta.get("com_no") or row.get("ref_no")
                        nat_meta = meta.get("nature") or meta.get("category")
                        cat_obj = meta.get("complaint_category")
                        if isinstance(cat_obj, dict) and cat_obj.get("name"):
                            nat_meta = cat_obj.get("name")
                        if not nat_meta or nat_meta in ("Facility Maintenance", "General Maintenance"):
                            nat_meta = "General"
                        local_candidates.append({
                            "com_no": cid_meta,
                            "complaint_id": cid_meta,
                            "complaint_category": {"name": nat_meta},
                            "nature": nat_meta,
                            "description": meta.get("description") or meta.get("details") or meta.get("updated_description") or "Maintenance request",
                            "details": meta.get("description") or meta.get("details") or meta.get("updated_description") or "Maintenance request",
                            "status": meta.get("status") or "In Progress",
                            "created_at": format_to_ist(meta.get("created_at") or row.get("timestamp")),
                            "updated_at": format_to_ist(meta.get("updated_at") or row.get("timestamp")),
                            "unitNo": meta.get("unit") or meta.get("unitNo") or "",
                            "reference_unit_no": meta.get("unit") or meta.get("unitNo") or "",
                            "mobile": meta.get("mobile") or meta.get("mobile_number") or "",
                            "company": meta.get("company") or meta.get("company_name") or "",
                        })
            except Exception:
                continue
    except Exception as audit_err:
        logger.debug(f"Could not load fallback audit tickets: {audit_err}")

    # Build dictionary of live Factech statuses from raw_list
    factech_live_map = {}
    for item in raw_list:
        if isinstance(item, dict):
            item_cid = str(item.get("com_no") or item.get("complaintId") or item.get("id") or "").strip().lstrip("#")
            if item_cid:
                factech_live_map[item_cid] = item

    # If local candidates exist, reconcile their status against live Factech map
    reconciled_local = []
    for loc in local_candidates:
        if not isinstance(loc, dict):
            continue
        loc_cid = str(loc.get("com_no") or loc.get("complaint_id") or loc.get("id") or "").strip().lstrip("#")
        if loc_cid in factech_live_map and isinstance(factech_live_map[loc_cid], dict):
            live_item = factech_live_map[loc_cid]
            live_status = live_item.get("status")
            if live_status:
                loc["status"] = live_status
            if live_item.get("closed_at"):
                loc["closed_at"] = format_to_ist(live_item.get("closed_at"))
            if live_item.get("tat"):
                loc["tat"] = live_item.get("tat")
            if live_item.get("remarks"):
                loc["remarks"] = live_item.get("remarks")
            if live_item.get("staff"):
                loc["staff"] = live_item.get("staff")
            live_cat = live_item.get("complaint_category") or {}
            live_nat = (live_cat.get("name") if isinstance(live_cat, dict) else None) or live_item.get("nature")
            if live_nat:
                loc["nature"] = live_nat
                loc["category"] = live_nat
                loc["complaint_category"] = {"name": live_nat}
        elif loc_cid and loc_cid not in factech_live_map:
            # If local candidate is NOT in recent Factech map, verify directly from Factech
            try:
                live_item = get_complaint_by_id(site_id, loc_cid, client_context=client_context, dt_hint=loc.get("created_at"))
                factech_live_map[loc_cid] = live_item
            except Exception as verify_err:
                logger.debug(f"Direct Factech verification for {loc_cid} failed: {verify_err}")
                factech_live_map[loc_cid] = None
                live_item = None

            if live_item and isinstance(live_item, dict):
                loc["status"] = live_item.get("status") or loc.get("status")
                if live_item.get("closed_at"):
                    loc["closed_at"] = format_to_ist(live_item.get("closed_at"))
                if live_item.get("tat"):
                    loc["tat"] = live_item.get("tat")
                if live_item.get("remarks"):
                    loc["remarks"] = live_item.get("remarks")
                if live_item.get("staff"):
                    loc["staff"] = live_item.get("staff")
                live_cat = live_item.get("complaint_category") or {}
                live_nat = (live_cat.get("name") if isinstance(live_cat, dict) else None) or live_item.get("nature")
                if live_nat:
                    loc["nature"] = live_nat
                    loc["category"] = live_nat
                    loc["complaint_category"] = {"name": live_nat}
        reconciled_local.append(loc)

    # Combine API and reconciled local complaints
    combined_raw = list(raw_list) + reconciled_local

    # Deduplicate and filter by tenant identity
    seen_ids = set()
    filtered = []

    for c in combined_raw:
        if not isinstance(c, dict):
            continue

        cid = str(c.get("com_no") or c.get("complaintId") or c.get("complaintNumber") or c.get("id") or "").strip()
        if not cid or cid in seen_ids:
            continue

        # Extract unit candidates accurately across all possible Factech structures
        c_units = []
        for u_raw in (c.get("unit"), c.get("user"), c.get("unitNo"), c.get("reference_unit_no"), c.get("flatNo")):
            if not u_raw:
                continue
            if isinstance(u_raw, dict):
                for k in ("flat_no", "display_unit_no", "name"):
                    val = u_raw.get(k)
                    if val:
                        c_units.append(str(val).strip().upper())
            else:
                c_units.append(str(u_raw).strip().upper())

        # Extract mobile
        created_by = c.get("created_by") or {}
        c_mobile_raw = created_by.get("phone_no") or c.get("mobile") or c.get("mobile_number") or c.get("phone") or ""
        c_mobile = "".join(ch for ch in str(c_mobile_raw) if ch.isdigit())

        # Extract company
        c_company = str(c.get("company") or c.get("company_name") or "").strip().lower()

        # Strict matching
        unit_match = False
        if target_unit and c_units:
            for c_unit in c_units:
                if target_unit == c_unit:
                    unit_match = True
                    break
                elif target_unit.isdigit() and c_unit.isdigit() and int(target_unit) == int(c_unit):
                    unit_match = True
                    break
                elif target_unit.lstrip("0") and c_unit.lstrip("0") and target_unit.lstrip("0") == c_unit.lstrip("0"):
                    unit_match = True
                    break
                elif len(target_unit) >= 3 and re.search(rf'\b{re.escape(target_unit)}\b', c_unit, re.IGNORECASE):
                    unit_match = True
                    break
                elif c_unit.startswith(f"{target_unit} ") or c_unit.endswith(f" {target_unit}") or f" {target_unit} " in c_unit:
                    unit_match = True
                    break

        mobile_match = bool(
            target_mobile_digits
            and len(target_mobile_digits) >= 10
            and len(c_mobile) >= 10
            and target_mobile_digits[-10:] == c_mobile[-10:]
        )

        company_match = bool(
            target_company
            and c_company
            and (target_company == c_company or target_company in c_company or c_company in target_company)
        )

        if unit_match or mobile_match or company_match:
            status = str(c.get("status") or "Open").strip()
            is_closed = status.lower() in ("closed", "resolved", "completed", "cancelled", "cancel")

            if active_only and is_closed:
                continue

            # Ensure timestamps are in IST
            if c.get("updated_at"):
                c["updated_at"] = format_to_ist(c["updated_at"])
            if c.get("created_at"):
                c["created_at"] = format_to_ist(c["created_at"])
            if c.get("updatedAt"):
                c["updatedAt"] = format_to_ist(c["updatedAt"])
            if c.get("createdAt"):
                c["createdAt"] = format_to_ist(c["createdAt"])

            seen_ids.add(cid)
            filtered.append(c)

    # Sort descending by creation date/time if available
    def _sort_key(item):
        d_val = item.get("created_at") or item.get("updated_at") or item.get("createdAt") or ""
        return str(d_val)

    filtered.sort(key=_sort_key, reverse=True)
    return filtered
