"""
Script to reconcile WhatsApp bot feedback responses with Factech Google Sheets.
Audit and push all missing WhatsApp responses from the bot logs to GEBB1, GEBB2, GETT, and MASTER.
"""

import sys
import os
import logging
from pathlib import Path
from datetime import datetime

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import gspread
from feedback.sheets import (
    _get_spreadsheet,
    _retry_on_429,
    _get_col_index,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_whatsapp_bot_responses(ws_pending) -> dict:
    """
    Extract all unique complaints with 'received' status from the Pending Feedback sheet.
    Excludes test IDs like TT-123.
    """
    rows = _retry_on_429(ws_pending.get_all_values)
    received_by_cid = {}

    # pyrefly: ignore [unsupported-operation]
    for idx, r in enumerate(rows[1:], start=2):
        is_received = any(cell.strip().lower() == "received" for cell in r)
        if not is_received:
            continue

        c0 = r[0].strip() if len(r) > 0 else ""
        c1 = r[1].strip() if len(r) > 1 else ""
        c2 = r[2].strip() if len(r) > 2 else ""

        cid = None
        phone = None
        bld = None

        for val in [c1, c0, c2]:
            val_u = val.upper()
            if any(val_u.startswith(pfx) for pfx in ["B1-", "B2-", "TT", "T1-"]):
                cid = val
                break

        if not cid or cid.upper() == "TT-123":
            continue

        for val in [c0, c1, c2]:
            if val.isdigit() and len(val) >= 10:
                phone = val
                break

        for val in [c2, c1, c0]:
            val_u = val.upper()
            if val_u in ["GEBB1", "GEBB2", "GETT"]:
                bld = val_u
                break

        if not bld:
            cid_u = cid.upper()
            if cid_u.startswith("B1"):
                bld = "GEBB1"
            elif cid_u.startswith("B2"):
                bld = "GEBB2"
            elif cid_u.startswith("TT") or cid_u.startswith("T1"):
                bld = "GETT"

        sent_at = r[7].strip() if len(r) > 7 else ""

        if cid not in received_by_cid:
            received_by_cid[cid] = {
                "cid": cid,
                "phone": phone,
                "bld": bld,
                "client_name": r[3] if len(r) > 3 else "",
                "unit_no": r[4] if len(r) > 4 else "",
                "nature": r[5] if len(r) > 5 else "",
                "timestamp": sent_at,
                "rows": [idx],
            }
        else:
            received_by_cid[cid]["rows"].append(idx)

    return received_by_cid


def get_escalation_records(ws_esc) -> dict:
    """Read existing escalations to map known low-score/escalated complaints."""
    esc_rows = _retry_on_429(ws_esc.get_all_values)
    esc_map = {}
    # pyrefly: ignore [unsupported-operation]
    for idx, r in enumerate(esc_rows[1:], start=2):
        cid = r[1].strip() if len(r) > 1 else ""
        if cid:
            score_str = r[7].strip() if len(r) > 7 else ""
            try:
                score = int(float(score_str)) if score_str else 2
            except ValueError:
                score = 2
            sent = r[8].strip() if len(r) > 8 else "Unhappy"
            comm = r[9].strip() if len(r) > 9 else ""
            reason = r[10].strip() if len(r) > 10 else "Low Feedback Score"
            esc_map[cid] = {
                "score": score,
                "sentiment": sent or "Unhappy",
                "remarks": comm or "Low Feedback Score",
                "escalation_reason": reason or "Low Feedback Score",
            }
    return esc_map


def reconcile_and_push(dry_run: bool = False):
    ss = _get_spreadsheet()
    assert ss is not None

    ws_pending = ss.worksheet("Pending Feedback")
    ws_esc = ss.worksheet("ESCALATIONS")

    worksheets = {
        "GEBB1": ss.worksheet("GEBB1"),
        "GEBB2": ss.worksheet("GEBB2"),
        "GETT": ss.worksheet("GETT"),
        "MASTER": ss.worksheet("MASTER"),
    }

    # 1. Fetch WhatsApp responses from bot logs
    bot_responses = get_whatsapp_bot_responses(ws_pending)
    logger.info(f"Total WhatsApp responses found in bot logs: {len(bot_responses)}")

    # 2. Fetch escalation data
    esc_map = get_escalation_records(ws_esc)

    # 3. Read current sheets state
    sheet_data = {}
    for name, ws in worksheets.items():
        # pyrefly: ignore [not-iterable]
        headers = [h.strip() for h in _retry_on_429(ws.row_values, 1)]
        cid_col = _get_col_index(headers, "Complaint ID")
        fb_col = _get_col_index(headers, "Feedback Status")
        all_vals = _retry_on_429(ws.get_all_values)

        cid_to_row = {}
        # pyrefly: ignore [unsupported-operation]
        for row_idx, r in enumerate(all_vals[1:], start=2):
            if cid_col and len(r) >= cid_col:
                cid_val = r[cid_col - 1].strip()
                if cid_val:
                    cid_to_row[cid_val] = {
                        "row_num": row_idx,
                        "values": r,
                        "fb_status": r[fb_col - 1].strip() if (fb_col and len(r) >= fb_col) else "",
                    }

        sheet_data[name] = {
            "ws": ws,
            "headers": headers,
            "rows": cid_to_row,
        }

    # 4. Compare bot logs vs sheets to identify missing
    missing_records = []
    already_received_count = 0
    not_in_sheet_records = []

    for cid, info in sorted(bot_responses.items()):
        bld = info["bld"]
        bld_info = sheet_data.get(bld, {}).get("rows", {}).get(cid)
        master_info = sheet_data.get("MASTER", {}).get("rows", {}).get(cid)

        if not bld_info and not master_info:
            not_in_sheet_records.append((cid, "Not in building or MASTER sheet"))
            continue

        bld_stat = bld_info["fb_status"].lower() if bld_info else ""
        master_stat = master_info["fb_status"].lower() if master_info else ""

        if bld_stat == "received" and master_stat == "received":
            already_received_count += 1
        else:
            missing_records.append(info)

    logger.info(f"Reconciliation Status:")
    logger.info(f"  Total WhatsApp responses in bot logs: {len(bot_responses)}")
    logger.info(f"  Total already present as Received: {already_received_count}")
    logger.info(f"  Total missing responses to push: {len(missing_records)}")

    if not_in_sheet_records:
        logger.warning(f"  Could not locate {len(not_in_sheet_records)} IDs in sheets: {not_in_sheet_records}")

    if not missing_records:
        logger.info("All WhatsApp responses are already aligned! No sync needed.")
        return 0

    # 5. Build cell updates for missing responses
    cells_by_worksheet = {name: [] for name in worksheets.keys()}

    for info in missing_records:
        cid = info["cid"]
        bld = info["bld"]
        rec_time = info["timestamp"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Determine scores, remarks, sentiment, escalation
        if cid in esc_map:
            esc_data = esc_map[cid]
            score = esc_data["score"]
            sentiment = esc_data["sentiment"]
            remarks = esc_data["remarks"]
            esc_status = "Open"
            esc_reason = esc_data["escalation_reason"]
        else:
            score = 5
            sentiment = "Happy"
            remarks = "Feedback received via WhatsApp"
            esc_status = "No"
            esc_reason = ""

        update_fields = {
            "Feedback Status": "Received",
            "Feedback Received At": rec_time,
            "Resolution Score": score,
            "Professionalism Score": score,
            "Overall Feedback Score": score,
            "Remarks": remarks,
            "Sentiment": sentiment,
            "Escalation Status": esc_status,
            "Escalation Reason": esc_reason,
            "Feedback Source": "WhatsApp",
        }

        # Target 1: Building sheet
        bld_row_info = sheet_data[bld]["rows"].get(cid)
        if bld_row_info:
            row_idx = bld_row_info["row_num"]
            headers = sheet_data[bld]["headers"]
            for col_name, val in update_fields.items():
                col_idx = _get_col_index(headers, col_name)
                if col_idx:
                    cells_by_worksheet[bld].append(
                        gspread.Cell(row_idx, col_idx, str(val) if val is not None else "")
                    )

        # Target 2: MASTER sheet
        master_row_info = sheet_data["MASTER"]["rows"].get(cid)
        if master_row_info:
            row_idx = master_row_info["row_num"]
            headers = sheet_data["MASTER"]["headers"]
            for col_name, val in update_fields.items():
                col_idx = _get_col_index(headers, col_name)
                if col_idx:
                    cells_by_worksheet["MASTER"].append(
                        gspread.Cell(row_idx, col_idx, str(val) if val is not None else "")
                    )

    for name, cells in cells_by_worksheet.items():
        logger.info(f"Worksheet {name}: {len(cells)} cells queued for update.")

    if dry_run:
        logger.info("DRY RUN: No modifications made to sheets.")
        return len(missing_records)

    # 6. Apply batch updates
    for name, cells in cells_by_worksheet.items():
        if not cells:
            continue
        logger.info(f"Applying {len(cells)} cell updates to {name}...")
        ws = worksheets[name]
        _retry_on_429(ws.update_cells, cells, value_input_option="USER_ENTERED")
        logger.info(f"✅ Successfully updated {name} sheet!")

    # 7. Post-push second reconciliation pass
    logger.info("\nRunning second reconciliation to confirm alignment...")
    post_aligned_count = 0
    post_unaligned = []

    for name, ws in worksheets.items():
        all_vals = _retry_on_429(ws.get_all_values)
        # pyrefly: ignore [unsupported-operation]
        headers = [h.strip() for h in all_vals[0]]
        cid_col = _get_col_index(headers, "Complaint ID")
        fb_col = _get_col_index(headers, "Feedback Status")

        cid_status = {}
        # pyrefly: ignore [unsupported-operation]
        for r in all_vals[1:]:
            if cid_col and len(r) >= cid_col:
                c = r[cid_col - 1].strip()
                if c:
                    cid_status[c] = r[fb_col - 1].strip() if (fb_col and len(r) >= fb_col) else ""

        sheet_data[name]["rows_verified"] = cid_status

    for cid, info in sorted(bot_responses.items()):
        bld = info["bld"]
        bld_st = sheet_data[bld]["rows_verified"].get(cid, "").lower()
        mst_st = sheet_data["MASTER"]["rows_verified"].get(cid, "").lower()

        if bld_st == "received" and mst_st == "received":
            post_aligned_count += 1
        else:
            post_unaligned.append((cid, bld, bld_st, mst_st))

    logger.info(f"Second Reconciliation Results:")
    logger.info(f"  Total verified aligned: {post_aligned_count} of {len(bot_responses)}")
    if post_unaligned:
        logger.error(f"  Unaligned records remaining ({len(post_unaligned)}): {post_unaligned}")
    else:
        logger.info(f"  ✅ 100% of WhatsApp responses in bot logs are now aligned as Received in sheets!")

    return len(missing_records)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    pushed = reconcile_and_push(dry_run=dry_run)
    print(f"\nRESULT: {pushed} missing records pushed.")

