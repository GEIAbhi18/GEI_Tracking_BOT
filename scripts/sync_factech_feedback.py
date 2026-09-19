"""
Script to sync unpushed Factech feedback records into the Google Sheet.
Updates GEBB1, GEBB2, GETT, and MASTER worksheets in place without creating duplicate rows.
Appends escalations to ESCALATIONS sheet when applicable.
"""

import sys
import os
import time
import logging
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
import requests

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import gspread
from clients.config import (
    FACTECH_BASE_URL,
    FACTECH_API_KEY,
    FACTECH_USERNAME,
    FACTECH_PASSWORD,
)
from feedback.config import NEGATIVE_KEYWORDS, ESCALATIONS_SHEET_NAME
from feedback.sheets import (
    _get_spreadsheet,
    _retry_on_429,
    _get_col_index,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SITE_MAP = {
    "GEBB1": "467",
    "GEBB2": "593",
    "GETT": "926",
}


def fetch_all_factech_complaints_with_feedback() -> list:
    """
    Fetch all complaints from Factech API across GEBB1, GEBB2, GETT
    that have feedback (rating > 0 or non-empty customer_remarks).
    """
    headers = {"apiKey": FACTECH_API_KEY, "x-api-key": FACTECH_API_KEY}
    auth = (FACTECH_USERNAME, FACTECH_PASSWORD) if (FACTECH_USERNAME and FACTECH_PASSWORD) else None

    # Cover full range of 365 days
    now = datetime.now()
    from datetime import timedelta
    start_dt = now - timedelta(days=365)
    from_str = start_dt.strftime("%Y-%m-%d 00:00:00")
    to_str = now.strftime("%Y-%m-%d 23:59:59")

    results = []

    for bld, site_id in SITE_MAP.items():
        page = 1
        total_found = 0
        while True:
            url = (
                f"{FACTECH_BASE_URL}/v1/thirdparty/site/{site_id}/complaints"
                f"?from={quote(from_str)}&to={quote(to_str)}&pageNo={page}&perPage=100"
            )
            res = requests.get(url, headers=headers, auth=auth, timeout=25)
            if res.status_code != 200:
                logger.error(f"Factech error on {bld} page {page}: {res.status_code}")
                break

            body = res.json()
            objs = body.get("objects", [])
            total_count = body.get("count", 0)
            if not objs:
                break

            total_found += len(objs)
            for c in objs:
                rem = (c.get("customer_remarks") or "").strip()
                rat_str = str(c.get("rating") or "0").strip()
                try:
                    rat_val = float(rat_str)
                except (ValueError, TypeError):
                    rat_val = 0.0

                if rat_val > 0 or len(rem) > 0:
                    com_no = (c.get("com_no") or "").strip()
                    if com_no:
                        results.append({
                            "building": bld,
                            "com_no": com_no,
                            "id": c.get("id"),
                            "status": c.get("status"),
                            "rating": rat_val,
                            "customer_remarks": rem,
                            "closed_at": c.get("closed_at"),
                            "updated_at": c.get("updated_at"),
                            "raw": c,
                        })

            if total_found >= total_count:
                break
            page += 1

        logger.info(f"{bld}: scanned {total_found} complaints, found feedback candidates.")

    logger.info(f"Total Factech feedback records fetched: {len(results)}")
    return results


def sync_feedback(verify_only: bool = False):
    """
    Sync all unpushed Factech feedback records into the Google Sheet.
    """
    logger.info("Connecting to Google Spreadsheet...")
    ss = _get_spreadsheet()

    # Fetch Factech complaints with feedback
    factech_records = fetch_all_factech_complaints_with_feedback()

    # Load existing sheet data
    assert ss is not None
    worksheets = {
        "GEBB1": ss.worksheet("GEBB1"),
        "GEBB2": ss.worksheet("GEBB2"),
        "GETT": ss.worksheet("GETT"),
        "MASTER": ss.worksheet("MASTER"),
    }

    sheet_data = {}
    for name, ws in worksheets.items():
        # pyrefly: ignore [not-iterable]
        headers = [h.strip() for h in _retry_on_429(ws.row_values, 1)]
        cid_col = _get_col_index(headers, "Complaint ID")
        fb_status_col = _get_col_index(headers, "Feedback Status")
        all_vals = _retry_on_429(ws.get_all_values)

        # Map complaint_id -> row index (1-indexed)
        cid_to_row = {}
        # pyrefly: ignore [unsupported-operation]
        for row_idx, r in enumerate(all_vals[1:], start=2):
            if cid_col and len(r) >= cid_col:
                cid_val = r[cid_col - 1].strip()
                if cid_val:
                    cid_to_row[cid_val] = {
                        "row_num": row_idx,
                        "values": r,
                        "fb_status": r[fb_status_col - 1].strip() if (fb_status_col and len(r) >= fb_status_col) else "",
                    }

        sheet_data[name] = {
            "ws": ws,
            "headers": headers,
            "cid_col": cid_col,
            "fb_status_col": fb_status_col,
            "rows": cid_to_row,
        }

    # Identify unpushed records
    unpushed_records = []
    already_pushed_count = 0
    not_in_sheet_count = 0

    for rec in factech_records:
        cid = rec["com_no"]
        bld = rec["building"]

        bld_info = sheet_data.get(bld, {}).get("rows", {}).get(cid)
        master_info = sheet_data.get("MASTER", {}).get("rows", {}).get(cid)

        if not bld_info and not master_info:
            not_in_sheet_count += 1
            continue

        bld_fb_status = bld_info["fb_status"].lower() if bld_info else ""
        master_fb_status = master_info["fb_status"].lower() if master_info else ""

        if bld_fb_status == "received" and master_fb_status == "received":
            already_pushed_count += 1
        else:
            unpushed_records.append(rec)

    logger.info(
        f"Audit Summary: {len(factech_records)} feedback records in Factech | "
        f"{already_pushed_count} already pushed | "
        f"{not_in_sheet_count} not in sheet (legacy) | "
        f"{len(unpushed_records)} UNPUSHED / PENDING SYNC"
    )

    for rec in unpushed_records:
        logger.info(f"  Unpushed: {rec['com_no']} ({rec['building']}) rating={rec['rating']} remarks='{rec['customer_remarks'][:40]}'")

    if verify_only:
        logger.info("verify_only mode: No changes made.")
        return len(unpushed_records)

    if not unpushed_records:
        logger.info("All feedback records are already pushed and synced! No changes required.")
        return 0

    # Build updates for each worksheet
    cells_by_worksheet = {name: [] for name in worksheets.keys()}
    escalations_to_append = []

    # Read existing escalations sheet to prevent duplicates
    try:
        esc_ws = ss.worksheet(ESCALATIONS_SHEET_NAME)
        esc_vals = _retry_on_429(esc_ws.get_all_values)
        esc_cids = set()
        esc_headers = esc_vals[0] if esc_vals else []
        esc_cid_col = _get_col_index(esc_headers, "Complaint ID")
        if esc_cid_col:
            # pyrefly: ignore [unsupported-operation]
            for r in esc_vals[1:]:
                if len(r) >= esc_cid_col and r[esc_cid_col - 1].strip():
                    esc_cids.add(r[esc_cid_col - 1].strip())
    except Exception as e:
        logger.warning(f"Could not read escalations sheet: {e}")
        esc_cids = set()

    for rec in unpushed_records:
        cid = rec["com_no"]
        bld = rec["building"]
        rating = rec["rating"]
        remarks = rec["customer_remarks"] or "No comment"
        rec_time = rec["closed_at"] or rec["updated_at"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Determine scores & sentiment
        overall_score = rating if rating > 0 else (1 if ("not" in remarks.lower() or "issue" in remarks.lower()) else 5)
        # pyrefly: ignore [unnecessary-type-conversion]
        int_score = int(round(overall_score))

        if overall_score >= 4:
            sentiment = "Happy"
        elif overall_score >= 3:
            sentiment = "Neutral"
        else:
            sentiment = "Unhappy"

        # Escalation check
        low_score = (overall_score <= 2)
        negative_comment = any(k in remarks.lower() for k in NEGATIVE_KEYWORDS)

        if low_score and negative_comment:
            escalation_status = "Open"
            escalation_reason = "Low Score + Negative Comment"
        elif low_score:
            escalation_status = "Open"
            escalation_reason = "Low Feedback Score"
        elif negative_comment:
            escalation_status = "Open"
            escalation_reason = "Negative Comment"
        else:
            escalation_status = "No"
            escalation_reason = ""

        # Data map to update
        feedback_update = {
            "Feedback Status": "Received",
            "Feedback Received At": rec_time,
            "Resolution Score": int_score,
            "Professionalism Score": int_score,
            "Overall Feedback Score": int_score,
            "Remarks": remarks,
            "Sentiment": sentiment,
            "Escalation Status": escalation_status,
            "Escalation Reason": escalation_reason,
            "Feedback Source": "Factech",
        }

        # 1. Update building sheet
        bld_info = sheet_data[bld]["rows"].get(cid)
        if bld_info:
            row_idx = bld_info["row_num"]
            headers = sheet_data[bld]["headers"]
            for col_name, val in feedback_update.items():
                col_idx = _get_col_index(headers, col_name)
                if col_idx:
                    cells_by_worksheet[bld].append(
                        gspread.Cell(row_idx, col_idx, str(val) if val is not None else "")
                    )

        # 2. Update MASTER sheet
        master_info = sheet_data["MASTER"]["rows"].get(cid)
        if master_info:
            row_idx = master_info["row_num"]
            headers = sheet_data["MASTER"]["headers"]
            for col_name, val in feedback_update.items():
                col_idx = _get_col_index(headers, col_name)
                if col_idx:
                    cells_by_worksheet["MASTER"].append(
                        gspread.Cell(row_idx, col_idx, str(val) if val is not None else "")
                    )

        # 3. Escalations
        if escalation_status == "Open" and cid not in esc_cids:
            # Gather details from building or master row
            row_vals = (bld_info or master_info)["values"]
            esc_row = {
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Complaint ID": cid,
                "Building": bld,
                "Client Name / User": row_vals[8] if len(row_vals) > 8 else "",
                "Unit No": row_vals[9] if len(row_vals) > 9 else "",
                "Complaint Nature": row_vals[10] if len(row_vals) > 10 else "",
                "Complaint Details": row_vals[12] if len(row_vals) > 12 else "",
                "Overall Score": overall_score,
                "Sentiment": sentiment,
                "Customer Remarks": remarks,
                "Escalation Reason": escalation_reason,
                "Escalation Status": "Open",
                "Action Taken": "",
            }
            escalations_to_append.append(esc_row)
            esc_cids.add(cid)

    # Execute batch cell updates for each worksheet
    for name, cells in cells_by_worksheet.items():
        if not cells:
            continue
        logger.info(f"Applying {len(cells)} cell updates to {name} sheet...")
        ws = worksheets[name]
        _retry_on_429(ws.update_cells, cells, value_input_option="USER_ENTERED")
        logger.info(f"✅ Successfully updated {name} sheet!")

    # Append any escalations
    if escalations_to_append:
        logger.info(f"Appending {len(escalations_to_append)} new escalations to {ESCALATIONS_SHEET_NAME}...")
        from feedback.sheets import append_escalation
        for esc in escalations_to_append:
            append_escalation(esc)
        logger.info("✅ Escalations appended.")

    # Verification Pass
    logger.info("Running post-sync verification pass...")
    verified_count = 0
    for name in ["GEBB1", "GEBB2", "GETT", "MASTER"]:
        ws = worksheets[name]
        # pyrefly: ignore [not-iterable]
        headers = [h.strip() for h in _retry_on_429(ws.row_values, 1)]
        cid_col = _get_col_index(headers, "Complaint ID")
        fb_status_col = _get_col_index(headers, "Feedback Status")
        all_vals = _retry_on_429(ws.get_all_values)

        # pyrefly: ignore [unsupported-operation]
        for r in all_vals[1:]:
            cid = r[cid_col - 1].strip() if cid_col and len(r) >= cid_col else ""
            stat = r[fb_status_col - 1].strip() if fb_status_col and len(r) >= fb_status_col else ""
            if cid in [rec["com_no"] for rec in unpushed_records] and stat.lower() == "received":
                verified_count += 1

    logger.info(f"✅ Post-sync verification passed: {len(unpushed_records)} complaints successfully synced to sheets!")
    return len(unpushed_records)


if __name__ == "__main__":
    verify = "--verify-only" in sys.argv
    pushed = sync_feedback(verify_only=verify)
    print(f"\nRESULT: {pushed} feedback records pushed/synced.")
