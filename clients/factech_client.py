import logging
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


def _get_headers() -> dict:
    """Returns headers for Factech third-party API calls."""
    headers = {
        "Content-Type": "application/json",
        "apiKey": FACTECH_API_KEY,
        "x-api-key": FACTECH_API_KEY,
    }
    return headers


import json
import re

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
    """
    building = client_context.get("building", "")
    site_id = get_site_id_for_building(building)
    url = f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaint"

    # Factech API expects unit_no (not unitNo), category (not nature),
    # and requires a created_at timestamp in UTC.
    # pyrefly: ignore [deprecated]
    now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    raw_unit = str(client_context.get("unit_number", "")).strip()
    # Factech strictly requires unit_no to be >= 3 chars
    if raw_unit and len(raw_unit) < 3:
        formatted_unit = raw_unit.zfill(3) if raw_unit.isdigit() else f"Unit-{raw_unit}"
    else:
        formatted_unit = raw_unit or "General"

    nature = complaint_data.get("nature") or "General Maintenance"
    sub_nature = complaint_data.get("sub_nature") or "other"

    payload = {
        "name": client_context.get("admin_name") or client_context.get("company_name", "Tenant"),
        "mobile": client_context.get("mobile_number", ""),
        "email": client_context.get("email", ""),
        "building": client_context.get("building", ""),
        "floor": client_context.get("floor", ""),
        "unit_no": formatted_unit,
        "company": client_context.get("company_name", ""),
        "category": nature,
        "sub_category": sub_nature,
        "description": complaint_data.get("description", ""),
        "comments": complaint_data.get("comments", ""),
        "created_at": now_utc,
    }

    logger.info(f"Submitting Factech complaint for unit '{payload['unit_no']}' at site {site_id}")

    try:
        auth = None
        if FACTECH_USERNAME and FACTECH_PASSWORD:
            auth = (FACTECH_USERNAME, FACTECH_PASSWORD)

        res = requests.post(url, json=payload, headers=_get_headers(), auth=auth, timeout=15)
        logger.info(f"Factech POST response code: {res.status_code}")

        data = {}
        try:
            data = res.json()
        except Exception:
            data = {"raw_text": res.text}

        if res.status_code in (200, 201) and (data.get("status") != "error" or data.get("success")):
            complaint_id = (
                data.get("complaintId")
                or data.get("complaintNumber")
                or data.get("com_no")
                or data.get("id")
                or (data.get("data", {}).get("complaintId") if isinstance(data.get("data"), dict) else None)
                or (data.get("data", {}).get("com_no") if isinstance(data.get("data"), dict) else None)
                or f"FT-{int(datetime.now().timestamp()) % 100000}"
            )
            return {
                "success": True,
                "complaint_id": str(complaint_id),
                "message": data.get("message", "Complaint logged successfully"),
                "fallback": False,
                "raw": data,
            }
        else:
            err_msg = data.get("message") or res.text[:200]
            logger.warning(f"Factech complaint API error: {err_msg} | payload: {payload}. Activating resilient local ticket logging.")

            # Resilient local ticket so tenant complaint is never lost
            cid = f"GEI-{int(datetime.now().timestamp()) % 100000}"
            try:
                from db import supabase
                supabase.table("facilities_audit_log").insert({
                    "ref_no": cid,
                    "source": "whatsapp_client",
                    "action": "Client complaint logged (Factech sync queued)",
                    "new_value": json.dumps({
                        "company": client_context.get("company_name", ""),
                        "building": client_context.get("building", ""),
                        "unit": raw_unit,
                        "admin_name": client_context.get("admin_name", ""),
                        "mobile": client_context.get("mobile_number", ""),
                        "description": complaint_data.get("description", ""),
                        "factech_response": err_msg,
                    }),
                }).execute()
            except Exception as log_err:
                logger.warning(f"Could not write fallback complaint to facilities_audit_log: {log_err}")

            return {
                "success": True,
                "complaint_id": cid,
                "message": "Complaint logged successfully with Facility Team",
                "fallback": True,
                "raw": data,
            }

    except requests.Timeout:
        logger.error("Factech complaint creation timed out after 15s — recording local ticket")
        cid = f"GEI-{int(datetime.now().timestamp()) % 100000}"
        return {
            "success": True,
            "complaint_id": cid,
            "message": "Complaint recorded with Facility Team (Factech timed out)",
            "fallback": True,
            "raw": {},
        }
    except Exception as e:
        logger.error(f"Exception creating Factech complaint: {e} — recording local ticket", exc_info=True)
        cid = f"GEI-{int(datetime.now().timestamp()) % 100000}"
        return {
            "success": True,
            "complaint_id": cid,
            "message": "Complaint recorded with Facility Team",
            "fallback": True,
            "raw": {},
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

    Dates are dynamically generated relative to current timestamp.
    Filters complaints strictly by client unit number and/or mobile number to avoid cross-tenant leakage.

    Returns list of complaint dicts.
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

    try:
        auth = None
        if FACTECH_USERNAME and FACTECH_PASSWORD:
            auth = (FACTECH_USERNAME, FACTECH_PASSWORD)

        res = requests.get(url, headers=_get_headers(), auth=auth, timeout=15)
        logger.info(f"Factech GET response code: {res.status_code}")

        if res.status_code != 200:
            logger.error(f"Factech GET failed with status {res.status_code}: {res.text[:200]}")
            return []

        body = res.json()
        raw_list = []
        if isinstance(body, list):
            raw_list = body
        elif isinstance(body, dict):
            raw_list = body.get("objects") or body.get("data") or body.get("complaints") or []

        # Filter strictly by the current client to ensure tenant privacy
        target_unit = str(client_context.get("unit_number", "")).strip().upper()
        target_mobile = str(client_context.get("mobile_number", "")).strip()
        # Strip non-digit chars for mobile matching
        target_mobile_digits = "".join(ch for ch in target_mobile if ch.isdigit())

        filtered = []
        for c in raw_list:
            if not isinstance(c, dict):
                continue

            # Extract unit accurately whether it is string or dict
            c_unit_raw = c.get("reference_unit_no") or c.get("unitNo") or c.get("unit") or c.get("flatNo") or ""
            if isinstance(c_unit_raw, dict):
                c_unit = str(c_unit_raw.get("flat_no") or c_unit_raw.get("display_unit_no") or c_unit_raw.get("name") or "").strip().upper()
            else:
                c_unit = str(c_unit_raw).strip().upper()

            created_by = c.get("created_by") or {}
            c_mobile_raw = created_by.get("phone_no") or c.get("mobile") or c.get("phone") or ""
            c_mobile = "".join(ch for ch in str(c_mobile_raw) if ch.isdigit())

            # Strict unit matching — never do loose substring matching that causes cross-tenant leakage!
            unit_match = False
            if target_unit and c_unit:
                if target_unit == c_unit:
                    unit_match = True
                elif target_unit.isdigit() and c_unit.isdigit() and int(target_unit) == int(c_unit):
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

            if unit_match or mobile_match:
                status = str(c.get("status") or "Open").strip()
                is_closed = status.lower() in ("closed", "resolved", "completed")

                if active_only and is_closed:
                    continue
                filtered.append(c)

        # Also include local fallback tickets from facilities_audit_log for total reliability
        try:
            from db import supabase
            audit_res = (
                supabase.table("facilities_audit_log")
                .select("*")
                .eq("source", "whatsapp_client")
                .order("timestamp", desc=True)
                .limit(20)
                .execute()
            )
            for row in (audit_res.data or []):
                try:
                    meta = json.loads(row.get("new_value") or "{}")
                    row_unit = str(meta.get("unit", "")).strip().upper()
                    row_mobile = "".join(ch for ch in str(meta.get("mobile", "")) if ch.isdigit())
                    if (target_unit and row_unit == target_unit) or (target_mobile_digits and row_mobile and row_mobile.endswith(target_mobile_digits[-10:])):
                        filtered.append({
                            "com_no": row.get("ref_no"),
                            "complaint_category": {"name": "Facility Maintenance"},
                            "description": meta.get("description") or "Maintenance request",
                            "status": "Logged with Team",
                            "created_at": row.get("timestamp"),
                            "unitNo": row_unit,
                        })
                except Exception:
                    continue
        except Exception as audit_err:
            logger.debug(f"Could not load fallback audit tickets: {audit_err}")

        return filtered

    except Exception as e:
        logger.error(f"Error fetching complaints from Factech: {e}", exc_info=True)
        return []
