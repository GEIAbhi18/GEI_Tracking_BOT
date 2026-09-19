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


def create_complaint(client_context: dict, complaint_data: dict) -> dict:
    """
    Creates a new complaint in Factech via:
    POST /v1/thirdparty/site/{siteId}/complaint

    client_context includes:
      - building, company_name, unit_number, admin_name, mobile_number, email, floor

    complaint_data includes:
      - nature, sub_nature, description, comments (optional)

    Returns dict:
      {"success": bool, "complaint_id": str, "message": str, "raw": dict}
    """
    building = client_context.get("building", "")
    site_id = get_site_id_for_building(building)
    url = f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaint"

    # Factech API expects unit_no (not unitNo), category (not nature),
    # and requires a created_at timestamp in UTC.
    # pyrefly: ignore [deprecated]
    now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "name": client_context.get("admin_name") or client_context.get("company_name", "Tenant"),
        "mobile": client_context.get("mobile_number", ""),
        "email": client_context.get("email", ""),
        "building": client_context.get("building", ""),
        "floor": client_context.get("floor", ""),
        "unit_no": client_context.get("unit_number", ""),
        "company": client_context.get("company_name", ""),
        "category": complaint_data.get("nature", "General"),
        "sub_category": complaint_data.get("sub_nature", "other"),
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
                # pyrefly: ignore [missing-attribute]
                or data.get("data", {}).get("complaintId")
                or f"FT-{int(datetime.now().timestamp()) % 100000}"
            )
            return {
                "success": True,
                "complaint_id": str(complaint_id),
                "message": data.get("message", "Complaint logged successfully"),
                "raw": data,
            }
        else:
            err_msg = data.get("message") or res.text[:200]
            logger.error(f"Factech complaint creation returned error: {err_msg} | payload: {payload}")
            return {
                "success": False,
                "complaint_id": None,
                "message": err_msg,
                "raw": data,
            }

    except requests.Timeout:
        logger.error("Factech complaint creation timed out after 15s")
        return {
            "success": False,
            "complaint_id": None,
            "message": "Factech service timed out. Please try again shortly.",
            "raw": {},
        }
    except Exception as e:
        logger.error(f"Exception creating Factech complaint: {e}", exc_info=True)
        return {
            "success": False,
            "complaint_id": None,
            "message": "Unable to communicate with Factech server.",
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

            # Factech returns reference_unit_no for unit, and created_by.phone_no for mobile
            c_unit = str(
                c.get("reference_unit_no") or c.get("unitNo") or c.get("unit") or c.get("flatNo") or ""
            ).strip().upper()
            created_by = c.get("created_by") or {}
            c_mobile_raw = created_by.get("phone_no") or c.get("mobile") or c.get("phone") or ""
            c_mobile = "".join(ch for ch in str(c_mobile_raw) if ch.isdigit())

            # Match on unit or mobile
            unit_match = bool(target_unit and (target_unit == c_unit or target_unit in c_unit))
            mobile_match = bool(target_mobile_digits and target_mobile_digits[-10:] in c_mobile[-10:] and len(c_mobile) >= 10)

            if unit_match or mobile_match:
                status = str(c.get("status") or "Open").strip()
                is_closed = status.lower() in ("closed", "resolved", "completed")

                if active_only and is_closed:
                    continue
                filtered.append(c)

        return filtered

    except Exception as e:
        logger.error(f"Error fetching complaints from Factech: {e}", exc_info=True)
        return []
