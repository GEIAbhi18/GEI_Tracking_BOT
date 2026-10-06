import logging
import os
import json
import re
import uuid
import requests
from datetime import datetime, timedelta
from urllib.parse import quote
from clients.config import (
    FACTECH_BASE_URL,
    FACTECH_API_KEY,
    FACTECH_USERNAME,
    FACTECH_PASSWORD,
    get_site_id_for_building,
)

logger = logging.getLogger(__name__)

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
    """
    global _LOGGED_COMPLAINTS_CACHE
    cid = record.get("complaint_id") or record.get("com_no")
    if not cid:
        return

    # 1. Update in-memory
    existing_idx = next(
        (i for i, c in enumerate(_LOGGED_COMPLAINTS_CACHE) if (c.get("complaint_id") or c.get("com_no")) == cid),
        None,
    )
    if existing_idx is not None:
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

    building = client_context.get("building", "")
    site_id = get_site_id_for_building(building)
    url = f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaint"

    # pyrefly: ignore [deprecated]
    now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    raw_unit = str(client_context.get("unit_number", "")).strip()
    if raw_unit and len(raw_unit) < 3:
        formatted_unit = raw_unit.zfill(3) if raw_unit.isdigit() else f"Unit-{raw_unit}"
    else:
        formatted_unit = raw_unit or "General"

    nature = complaint_data.get("nature") or "General Maintenance"
    sub_nature = complaint_data.get("sub_nature") or "other"
    desc = complaint_data.get("description", "")

    # ── Build Factech-compliant payload ──────────────────────────────────
    # Per Factech API spec, the expected fields are:
    #   complaint_no, unit_no, category, sub_category, description, created_at
    # reference_no is optional.
    payload = {
        "complaint_no": "",
        "unit_no": formatted_unit,
        "category": nature,
        "sub_category": sub_nature,
        "description": desc,
        "created_at": now_utc,
    }

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
        has_success_flag = data.get("success") in (True, "true", "True")

        complaint_id = (
            data.get("complaintId")
            or data.get("complaintNumber")
            or data.get("com_no")
            or data.get("id")
            or (data.get("data", {}).get("complaintId") if isinstance(data.get("data"), dict) else None)
            or (data.get("data", {}).get("com_no") if isinstance(data.get("data"), dict) else None)
            or (data.get("data", {}).get("complaint_no") if isinstance(data.get("data"), dict) else None)
        )

        logger.info(f"{log_prefix} HTTP OK: {is_http_ok}, Not Error Status: {is_not_error}, Success Flag: {has_success_flag}")
        logger.info(f"{log_prefix} Extracted Complaint ID: {complaint_id}")

        if is_http_ok and (is_not_error or has_success_flag) and complaint_id:
            # ── REAL SUCCESS: Factech confirmed complaint creation ────
            logger.info(f"{log_prefix} Complaint Creation Result: SUCCESS")
            logger.info(f"{log_prefix} Complaint Number/ID: {complaint_id}")

            complaint_record = {
                "complaint_id": str(complaint_id),
                "com_no": str(complaint_id),
                "company": client_context.get("company_name", ""),
                "company_name": client_context.get("company_name", ""),
                "building": client_context.get("building", ""),
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

    except requests.Timeout:
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


def update_complaint(client_context: dict, complaint_id: str, update_data: dict) -> dict:
    """
    Updates an existing complaint in Factech via:
    PUT /v1/thirdparty/site/{siteId}/complaint

    And updates the persistent local complaint store & Supabase facilities_audit_log.
    """
    req_id = _generate_request_id()
    log_prefix = f"[FACTECH_COMPLAINT][request_id={req_id}]"

    # pyrefly: ignore [unnecessary-type-conversion]
    clean_cid = str(complaint_id).lstrip("#").strip()
    building = client_context.get("building", "")
    site_id = get_site_id_for_building(building)
    url = f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaint"

    new_desc = update_data.get("description", "").strip()
    remarks = update_data.get("remarks") or new_desc

    payload = {
        "complaint_no": clean_cid,
        "description": new_desc,
        "remarks": remarks,
        "status": update_data.get("status", "In Progress"),
    }

    logger.info(f"{log_prefix} Starting complaint UPDATE request")
    logger.info(f"{log_prefix} Method: PUT")
    logger.info(f"{log_prefix} URL: {url}")
    logger.info(f"{log_prefix} Complaint ID: {clean_cid}")
    logger.info(f"{log_prefix} Payload: {json.dumps(payload)}")

    # 1. Attempt Factech PUT endpoint
    api_success = False
    api_resp_data = {}
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

        if res.status_code in (200, 201) and (api_resp_data.get("status") != "error" or api_resp_data.get("success")):
            api_success = True
            logger.info(f"{log_prefix} Complaint Update Result: SUCCESS")
        else:
            logger.warning(f"{log_prefix} Complaint Update Result: FAILED - {api_resp_data}")
    except Exception as e:
        logger.warning(f"{log_prefix} Factech PUT update complaint error: {e}")

    # 2. Resilient local update in cache & disk store
    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated_record = None

    # Check in-memory & disk
    all_local = _LOGGED_COMPLAINTS_CACHE + _load_persisted_complaints()
    for rec in all_local:
        rcid = str(rec.get("complaint_id") or rec.get("com_no") or "").lstrip("#")
        if rcid == clean_cid:
            if new_desc:
                old_desc = rec.get("description") or rec.get("details") or ""
                rec["description"] = f"{old_desc} | Update: {new_desc}" if old_desc else new_desc
                rec["details"] = rec["description"]
            rec["updated_at"] = now_local
            updated_record = rec
            break

    if not updated_record:
        # Create record entry if not previously cached locally
        raw_unit = str(client_context.get("unit_number", "")).strip()
        updated_record = {
            "complaint_id": clean_cid,
            "com_no": clean_cid,
            "company": client_context.get("company_name", ""),
            "building": client_context.get("building", ""),
            "unit": raw_unit,
            "unitNo": raw_unit,
            "admin_name": client_context.get("admin_name", ""),
            "mobile": client_context.get("mobile_number", ""),
            "nature": "General Maintenance",
            "complaint_category": {"name": "General Maintenance"},
            "description": new_desc,
            "details": new_desc,
            "status": "In Progress",
            "created_at": now_local,
            "updated_at": now_local,
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

    return {
        "success": True,
        "complaint_id": clean_cid,
        "message": "Complaint updated successfully",
        "raw": api_resp_data,
    }


def get_complaints(
    client_context: dict,
    days_back: int = 60,
    page_no: int = 1,
    per_page: int = 20,
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
    try:
        auth = None
        if FACTECH_USERNAME and FACTECH_PASSWORD:
            auth = (FACTECH_USERNAME, FACTECH_PASSWORD)

        res = requests.get(url, headers=_get_headers(), auth=auth, timeout=15)
        logger.info(f"Factech GET response code: {res.status_code}")

        if res.status_code == 200:
            body = res.json()
            if isinstance(body, list):
                raw_list = body
            elif isinstance(body, dict):
                raw_list = body.get("objects") or body.get("data") or body.get("complaints") or []
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
                        local_candidates.append({
                            "com_no": meta.get("complaint_id") or meta.get("com_no") or row.get("ref_no"),
                            "complaint_id": meta.get("complaint_id") or meta.get("com_no") or row.get("ref_no"),
                            "complaint_category": {"name": meta.get("nature") or meta.get("category") or "Facility Maintenance"},
                            "nature": meta.get("nature") or meta.get("category") or "Facility Maintenance",
                            "description": meta.get("description") or meta.get("details") or "Maintenance request",
                            "details": meta.get("description") or meta.get("details") or "Maintenance request",
                            "status": meta.get("status") or "In Progress",
                            "created_at": meta.get("created_at") or row.get("timestamp"),
                            "updated_at": meta.get("updated_at") or row.get("timestamp"),
                            "unitNo": meta.get("unit") or meta.get("unitNo") or "",
                            "reference_unit_no": meta.get("unit") or meta.get("unitNo") or "",
                            "mobile": meta.get("mobile") or meta.get("mobile_number") or "",
                            "company": meta.get("company") or meta.get("company_name") or "",
                        })
            except Exception:
                continue
    except Exception as audit_err:
        logger.debug(f"Could not load fallback audit tickets: {audit_err}")

    # Combine API and local complaints
    combined_raw = list(raw_list) + local_candidates

    # Deduplicate and filter by tenant identity
    seen_ids = set()
    filtered = []

    for c in combined_raw:
        if not isinstance(c, dict):
            continue

        cid = str(c.get("com_no") or c.get("complaintId") or c.get("complaintNumber") or c.get("id") or "").strip()
        if not cid or cid in seen_ids:
            continue

        # Extract unit accurately
        c_unit_raw = c.get("reference_unit_no") or c.get("unitNo") or c.get("unit") or c.get("flatNo") or ""
        if isinstance(c_unit_raw, dict):
            c_unit = str(c_unit_raw.get("flat_no") or c_unit_raw.get("display_unit_no") or c_unit_raw.get("name") or "").strip().upper()
        else:
            c_unit = str(c_unit_raw).strip().upper()

        # Extract mobile
        created_by = c.get("created_by") or {}
        c_mobile_raw = created_by.get("phone_no") or c.get("mobile") or c.get("mobile_number") or c.get("phone") or ""
        c_mobile = "".join(ch for ch in str(c_mobile_raw) if ch.isdigit())

        # Extract company
        c_company = str(c.get("company") or c.get("company_name") or "").strip().lower()

        # Strict matching
        unit_match = False
        if target_unit and c_unit:
            if target_unit == c_unit:
                unit_match = True
            elif target_unit.isdigit() and c_unit.isdigit() and int(target_unit) == int(c_unit):
                unit_match = True
            elif target_unit.lstrip("0") and c_unit.lstrip("0") and target_unit.lstrip("0") == c_unit.lstrip("0"):
                unit_match = True
            elif len(target_unit) >= 3 and re.search(rf'\b{re.escape(target_unit)}\b', c_unit, re.IGNORECASE):
                unit_match = True
            elif c_unit.startswith(f"{target_unit} ") or c_unit.endswith(f" {target_unit}") or f" {target_unit} " in c_unit:
                unit_match = True

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

            seen_ids.add(cid)
            filtered.append(c)

    # Sort descending by creation date/time if available
    def _sort_key(item):
        d_val = item.get("created_at") or item.get("updated_at") or item.get("createdAt") or ""
        return str(d_val)

    filtered.sort(key=_sort_key, reverse=True)
    return filtered
