from __future__ import annotations

"""
Facilities Module — Daily EOD Report Generator
================================================
Generates 'Facilities_Report_EOD.pdf' specifically for Kanav (Facilities Director)
and the Facilities team.

Features:
- Live Google Sheets data fetching across all building tabs (GEBB1, GEBB2, GETT, Common)
- Local row_cache fallback if Google Sheets is unreachable
- Professional layout with FPDF matching the GEI design system
- Summary KPIs (Total, Red/Critical, Amber/Delayed, Green/On Track, Completed, Pending)
- Building groupings with RAG statistics
- Individual task tables with progress bars, delay days, latest notes, and attachment links
- Logical sorting: Red/Critical → Amber/Delayed → Green/On Track → Completed
- Automated 6:00 PM IST dispatch and on-demand trigger
"""

import os
import re
import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime, date
import pytz
from collections import defaultdict
from fpdf import FPDF

from db import supabase
from config import TIMEZONE
from facilities.config import (
    BUILDING_TABS,
    COLUMN_MAP,
    CLOSED_STATUSES,
)

logger = logging.getLogger(__name__)

# Color Palette (Matching GEI Design System)
COLORS = {
    "HEADER_BG": (31, 95, 160),        # Professional Blue #1F5FA0
    "HEADER_LIGHT": (220, 232, 246),   # Soft Blue Accent
    "TEXT_DARK": (33, 37, 41),         # Charcoal #212529
    "TEXT_GREY": (108, 117, 125),      # Medium Grey #6C757D
    "LINE_GREY": (222, 226, 230),      # Border Grey #DEE2E6
    "ZEBRA_BG": (248, 249, 250),       # Off-white / light grey
    "CARD_BG": (241, 245, 249),        # Light slate
    "RED": (217, 48, 37),              # Critical / Overdue #D93025
    "RED_BG": (253, 237, 236),         # Light red
    "AMBER": (227, 116, 0),            # Delayed / Due Today #E37400
    "AMBER_BG": (254, 243, 232),       # Light amber
    "GREEN": (30, 142, 62),            # On Track / Completed #1E8E3E
    "GREEN_BG": (230, 244, 234),       # Light green
    "BLUE": (26, 115, 232),            # Active Blue #1A73E8
    "WHITE": (255, 255, 255),
}

BUILDING_DISPLAY_NAMES = {
    "GEBB1": "Bay 1 (GEBB1)",
    "GEBB2": "Bay 2 (GEBB2)",
    "GETT": "Tech Tower (GETT)",
    "Common": "Common Areas",
}


def clean_pdf_text(text) -> str:
    """Sanitize unicode strings for latin-1 encoding in FPDF."""
    if text is None:
        return "-"
    text = str(text)
    replacements = {
        "\u2014": "-", "\u2013": "-", "\u2022": "*",
        "\u00b7": "|", "\u201c": "\"", "\u201d": "\"",
        "\u2018": "'", "\u2019": "'", "\u2192": "->",
        "\u2705": "[x]", "\u274c": "[!]", "\U0001f3d7": "",
        "\u2026": "...", "—": "-", "–": "-",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


def _parse_date_safe(date_str: str) -> date | None:
    """Parse various date string formats into a date object."""
    if not date_str or not str(date_str).strip():
        return None
    cleaned = str(date_str).strip()
    formats = [
        "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y",
        "%d %B %Y", "%d %b %Y", "%Y/%m/%d", "%d-%b-%y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    return None


def calculate_task_rag(task: dict, today_date: date = None) -> tuple:
    """
    Calculate RAG priority status and delay days for a Facilities task.
    
    Returns:
        (rag_status, delay_days)
        rag_status in ("RED", "AMBER", "GREEN")
    """
    if today_date is None:
        today_date = date.today()

    status = (task.get("status") or "Open").strip()
    status_lower = status.lower()

    # If completed/closed -> Green
    if status in CLOSED_STATUSES or status_lower in ("closed", "completed", "done"):
        return ("GREEN", 0)

    target_date_val = _parse_date_safe(task.get("planned_date") or task.get("target_date"))
    created_date_val = _parse_date_safe(task.get("created_date"))

    # Delay days from explicit field or calculated
    raw_delay = str(task.get("delay_days") or "").strip()
    delay_days = 0
    if raw_delay and raw_delay.replace("-", "").isdigit():
        delay_days = max(0, int(raw_delay))
    elif target_date_val and today_date > target_date_val:
        delay_days = (today_date - target_date_val).days

    blocker = (task.get("blocker") or "").strip().lower()
    has_blocker = blocker and blocker not in ("none", "null", "no", "—", "-")

    # Priority Rules:
    # 1. Overdue or explicit delay -> RED
    if delay_days > 0 or (target_date_val and target_date_val < today_date):
        return ("RED", delay_days if delay_days > 0 else (today_date - target_date_val).days)

    # 2. Due today or has active blocker or On Hold -> AMBER
    if (target_date_val and target_date_val == today_date) or has_blocker or status_lower == "on hold":
        return ("AMBER", 0)

    # 3. Otherwise -> GREEN (On track / Future)
    return ("GREEN", 0)


def calculate_task_progress(task: dict) -> int:
    """Derive progress percentage (0-100) from task status/updates."""
    raw_prog = task.get("progress")
    if raw_prog is not None and str(raw_prog).replace("%", "").strip().isdigit():
        return min(100, max(0, int(str(raw_prog).replace("%", "").strip())))

    status = (task.get("status") or "").strip().lower()
    if status in ("closed", "completed", "done"):
        return 100
    elif status == "wip":
        return 50
    elif status == "on hold":
        return 25
    return 0


# ── Live Data Fetching ───────────────────────────────────────────────────────

def fetch_live_facilities_tasks(today_date: date = None) -> list:
    """
    Fetch all Facilities tasks directly from live Google Sheets tabs.
    Falls back to Supabase row_cache if Sheets API is unavailable.
    
    Returns list of standardized task dicts.
    """
    if today_date is None:
        today_date = date.today()

    all_tasks = []
    sheets_success = False

    # 1. Try reading live from Google Sheets
    try:
        from facilities.sheets_client import _get_worksheet, _retry_on_429, _row_to_dict

        for building in BUILDING_TABS:
            try:
                ws = _get_worksheet(building)
                raw_rows = _retry_on_429(ws.get_all_values)
                if not raw_rows or len(raw_rows) < 2:
                    continue  # Header only

                data_rows = raw_rows[1:]  # skip header
                for row_vals in data_rows:
                    if not row_vals or not row_vals[0] or not str(row_vals[0]).strip():
                        continue  # skip empty
                    
                    row_dict = _row_to_dict(row_vals, building)
                    row_dict["building"] = building
                    row_dict["ref_no"] = str(row_vals[0]).strip()
                    all_tasks.append(row_dict)
                sheets_success = True
            except Exception as bldg_err:
                logger.warning(f"Live Sheet read failed for tab {building}: {bldg_err}")

    except Exception as sheets_err:
        logger.error(f"Live Google Sheets connection failed: {sheets_err}")
        sheets_success = False

    # 2. If Sheets failed or returned empty, fallback to local row_cache
    if not sheets_success or not all_tasks:
        logger.info("Falling back to row_cache for Facilities tasks...")
        try:
            res = supabase.table("row_cache").select("*").execute()
            if res.data:
                all_tasks = res.data
        except Exception as cache_err:
            logger.error(f"row_cache fallback also failed: {cache_err}")

    # 3. Enrich with attachments from Supabase
    attachments_map = defaultdict(list)
    try:
        att_res = supabase.table("facilities_attachments").select("ref_no, file_url").execute()
        if att_res.data:
            for item in att_res.data:
                if item.get("ref_no") and item.get("file_url"):
                    attachments_map[item["ref_no"]].append(item["file_url"])
    except Exception as att_err:
        logger.warning(f"Could not load attachments: {att_err}")

    # 4. Standardize fields and compute RAG + Progress
    standardized = []
    for t in all_tasks:
        ref_no = t.get("ref_no", "").strip()
        if not ref_no:
            continue

        building = t.get("building")
        if not building:
            # Infer from ref_no prefix (e.g. GEBB1-001 -> GEBB1)
            prefix = ref_no.split("-")[0].upper()
            building = "GEBB1" if "GEBB1" in prefix else ("GEBB2" if "GEBB2" in prefix else ("GETT" if "GETT" in prefix else "Common"))

        rag_status, delay_days = calculate_task_rag(t, today_date)
        progress = calculate_task_progress(t)
        proof_urls = attachments_map.get(ref_no, [])

        standardized.append({
            "ref_no": ref_no,
            "building": building,
            "type": t.get("type") or "—",
            "issue_action": t.get("issue_action") or "—",
            "latest_update": t.get("latest_update") or "—",
            "added_by": t.get("last_modified_by_at") or t.get("added_by") or "—",
            "owner": t.get("owner") or "—",
            "created_date": t.get("created_date") or "—",
            "planned_date": t.get("planned_date") or t.get("target_date") or "—",
            "target_date": t.get("planned_date") or t.get("target_date") or "—",
            "estimated_completion_date": t.get("estimated_completion_date") or "—",
            "actual_completion_date": t.get("actual_completion_date") or "—",
            "delay_days": delay_days,
            "status": t.get("status") or "Open",
            "rag": rag_status,
            "progress": progress,
            "blocker": t.get("blocker") or "—",
            "proof_url": proof_urls[0] if proof_urls else None,
        })

    return standardized


# ── PDF Generation ───────────────────────────────────────────────────────────

class FacilitiesPDFReport(FPDF):
    """Custom FPDF subclass with standard GEI Facilities header & footer."""

    def footer(self):
        self.set_y(-12)
        self.set_draw_color(*COLORS["LINE_GREY"])
        self.set_line_width(0.3)
        self.line(10, self.h - 15, self.w - 10, self.h - 15)

        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*COLORS["TEXT_GREY"])
        footer_text = "GEI Tracking Bot | Auto-generated | Confidential | Do not distribute"
        self.cell(0, 8, clean_pdf_text(footer_text), align="C")


def generate_facilities_eod_pdf(tasks: list = None, output_path: str = None) -> str:
    """
    Generate 'Facilities_Report_EOD.pdf' from live Facilities tasks.
    
    Args:
        tasks: Optional pre-fetched task list (fetches live if None)
        output_path: Optional custom destination path
        
    Returns:
        Absolute filepath to the generated PDF.
    """
    if output_path is None:
        output_path = "/tmp/Facilities_Report_EOD.pdf"

    # 1. Fetch live data if not provided
    local_tz = pytz.timezone(TIMEZONE or "Asia/Kolkata")
    now_local = datetime.now(local_tz)
    today_date = now_local.date()

    if tasks is None:
        tasks = fetch_live_facilities_tasks(today_date)

    # 2. Compute Summary KPIs
    total_tasks = len(tasks)
    red_count = sum(1 for t in tasks if t["rag"] == "RED")
    amber_count = sum(1 for t in tasks if t["rag"] == "AMBER")
    green_count = sum(1 for t in tasks if t["rag"] == "GREEN")
    completed_count = sum(1 for t in tasks if t["status"].lower() in ("closed", "completed", "done"))
    pending_count = total_tasks - completed_count

    # 3. Initialize PDF
    pdf = FacilitiesPDFReport(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    def check_space(needed_h):
        if pdf.get_y() + needed_h > pdf.page_break_trigger:
            pdf.add_page()

    # ── Top Header Section ─────────────────────────────────────────────────
    date_str = now_local.strftime("%d %B %Y")
    time_str = "06:00 PM IST" if now_local.hour == 18 else now_local.strftime("%I:%M %p %Z")

    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*COLORS["TEXT_DARK"])
    pdf.cell(105, 12, "Facilities EOD Report", new_x="RIGHT", new_y="TOP")

    # Date / Time Box on Right
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*COLORS["TEXT_DARK"])
    pdf.set_x(-75)
    pdf.cell(65, 5, date_str, new_x="LMARGIN", new_y="NEXT", align="R")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*COLORS["TEXT_GREY"])
    pdf.set_x(-75)
    pdf.cell(65, 5, f"Generated at {time_str}", new_x="LMARGIN", new_y="NEXT", align="R")

    pdf.ln(1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*COLORS["TEXT_GREY"])
    pdf.cell(0, 4, clean_pdf_text("GEI Facilities | Auto-generated | Confidential"), new_x="LMARGIN", new_y="NEXT")

    # Header Accent Divider
    pdf.set_draw_color(*COLORS["HEADER_BG"])
    pdf.set_line_width(0.8)
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(6)

    # ── Facilities Summary KPI Strip ───────────────────────────────────────
    check_space(22)
    summary_y = pdf.get_y()

    # Summary Section Title
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*COLORS["HEADER_BG"])
    pdf.cell(0, 5, "Facilities Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    # 6 KPI Cards (Total, Red, Amber, Green, Completed, Pending)
    kpis = [
        {"label": "Total Tasks", "val": str(total_tasks), "color": COLORS["TEXT_DARK"], "bg": COLORS["CARD_BG"]},
        {"label": "Red / Critical", "val": str(red_count), "color": COLORS["RED"], "bg": COLORS["RED_BG"]},
        {"label": "Amber / Delayed", "val": str(amber_count), "color": COLORS["AMBER"], "bg": COLORS["AMBER_BG"]},
        {"label": "Green / On Track", "val": str(green_count), "color": COLORS["GREEN"], "bg": COLORS["GREEN_BG"]},
        {"label": "Completed", "val": str(completed_count), "color": COLORS["GREEN"], "bg": COLORS["GREEN_BG"]},
        {"label": "Pending", "val": str(pending_count), "color": COLORS["BLUE"], "bg": COLORS["HEADER_LIGHT"]},
    ]

    card_w = 30
    card_h = 12
    gap = 2
    x_start = 10
    kpi_y = pdf.get_y()

    for idx, kpi in enumerate(kpis):
        x = x_start + idx * (card_w + gap)

        pdf.set_fill_color(*kpi["bg"])
        pdf.set_draw_color(*COLORS["LINE_GREY"])
        pdf.set_line_width(0.2)
        pdf.rect(x, kpi_y, card_w, card_h, style="FD")

        # Number
        pdf.set_xy(x, kpi_y + 1)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*kpi["color"])
        pdf.cell(card_w, 5, kpi["val"], align="C")

        # Label
        pdf.set_xy(x, kpi_y + 6.5)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(card_w, 4, clean_pdf_text(kpi["label"]), align="C")

    pdf.set_y(kpi_y + card_h + 4)

    # ── Group by Building and Render Tables ────────────────────────────────
    # Group tasks
    building_tasks = defaultdict(list)
    for t in tasks:
        bldg = t.get("building") or "Common"
        building_tasks[bldg].append(t)

    # Sorting priority inside each building:
    # 1. Red (Critical/Overdue)
    # 2. Amber (Delayed/Due Today)
    # 3. Green (On Track)
    # 4. Completed
    def task_sort_key(t):
        is_closed = 1 if t["status"].lower() in ("closed", "completed", "done") else 0
        rag_weight = {"RED": 0, "AMBER": 1, "GREEN": 2}.get(t["rag"], 3)
        delay_weight = -t.get("delay_days", 0)
        return (is_closed, rag_weight, delay_weight, t.get("planned_date") or t.get("target_date") or "9999")

    # Table Column Specifications (Total width = 190mm)
    COL_WIDTHS = {
        "issue": 46,      # Task / Issue
        "type": 20,       # Project / Type
        "owner": 24,      # Owner
        "deadline": 18,   # Target Date
        "delay": 14,      # Delay Days
        "progress": 22,   # Progress %
        "rag": 16,        # RAG Status
        "note": 18,       # Latest Update
        "proof": 12,      # Proof Link
    }

    for bldg_code in BUILDING_TABS:
        bldg_name = BUILDING_DISPLAY_NAMES.get(bldg_code, bldg_code)
        b_tasks = building_tasks.get(bldg_code, [])

        check_space(22)

        # Count RAG for this building
        b_red = sum(1 for t in b_tasks if t["rag"] == "RED")
        b_amber = sum(1 for t in b_tasks if t["rag"] == "AMBER")
        b_green = sum(1 for t in b_tasks if t["rag"] == "GREEN")

        # Building Section Header
        pdf.set_fill_color(*COLORS["HEADER_LIGHT"])
        pdf.set_draw_color(*COLORS["HEADER_BG"])
        pdf.set_line_width(0.4)
        pdf.rect(10, pdf.get_y(), 190, 8, style="F")
        pdf.line(10, pdf.get_y(), 10, pdf.get_y() + 8)  # left accent bar

        pdf.set_xy(12, pdf.get_y())
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*COLORS["HEADER_BG"])
        pdf.cell(75, 8, clean_pdf_text(bldg_name), new_x="RIGHT", new_y="TOP")

        # RAG stats on header right
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*COLORS["RED"])
        pdf.cell(7, 8, str(b_red), align="R")
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(9, 8, " Red", align="L")

        pdf.set_text_color(*COLORS["AMBER"])
        pdf.cell(7, 8, str(b_amber), align="R")
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(11, 8, " Amber", align="L")

        pdf.set_text_color(*COLORS["GREEN"])
        pdf.cell(7, 8, str(b_green), align="R")
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(11, 8, " Green", align="L")

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*COLORS["TEXT_GREY"])
        pdf.cell(0, 8, f"({len(b_tasks)} tasks)", new_x="LMARGIN", new_y="NEXT", align="R")

        pdf.ln(1)

        if not b_tasks:
            # Grey 'No Tasks' placeholder
            check_space(8)
            pdf.set_fill_color(250, 250, 250)
            pdf.set_draw_color(*COLORS["LINE_GREY"])
            pdf.set_line_width(0.2)
            pdf.rect(10, pdf.get_y(), 190, 7, style="FD")
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(*COLORS["TEXT_GREY"])
            pdf.set_xy(14, pdf.get_y())
            pdf.cell(180, 7, "No tasks recorded for this building", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
            continue

        # Sort tasks
        b_tasks.sort(key=task_sort_key)

        # ── Table Header ───────────────────────────────────────────────────
        check_space(14)
        pdf.set_fill_color(*COLORS["HEADER_BG"])
        pdf.set_text_color(*COLORS["WHITE"])
        pdf.set_font("Helvetica", "B", 8)

        cols = [
            ("Task / Issue", COL_WIDTHS["issue"], "L"),
            ("Type", COL_WIDTHS["type"], "C"),
            ("Owner", COL_WIDTHS["owner"], "L"),
            ("Planned Date", COL_WIDTHS["deadline"], "C"),
            ("Delay", COL_WIDTHS["delay"], "C"),
            ("Progress", COL_WIDTHS["progress"], "C"),
            ("Priority", COL_WIDTHS["rag"], "C"),
            ("Latest Note", COL_WIDTHS["note"], "L"),
            ("Proof", COL_WIDTHS["proof"], "C"),
        ]

        for label, width, align in cols:
            pdf.cell(width, 7, label, fill=True, border=0, align=align)
        pdf.ln(7)

        # ── Table Rows ─────────────────────────────────────────────────────
        for idx, t in enumerate(b_tasks):
            check_space(11)

            fill = (idx % 2 != 0)
            row_bg = COLORS["ZEBRA_BG"] if fill else COLORS["WHITE"]
            pdf.set_fill_color(*row_bg)
            pdf.set_draw_color(*COLORS["LINE_GREY"])
            pdf.set_line_width(0.15)

            y_row = pdf.get_y()
            row_h = 9

            # 1. Task / Issue (Ref No + Title)
            ref = t.get("ref_no", "")
            issue = t.get("issue_action", "")
            issue_display = f"{ref}: {issue}" if ref else issue
            if len(issue_display) > 34:
                issue_display = issue_display[:32] + ".."

            pdf.set_xy(10, y_row)
            pdf.set_fill_color(*row_bg)
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(*COLORS["TEXT_DARK"])
            pdf.cell(COL_WIDTHS["issue"], row_h, clean_pdf_text(issue_display), fill=True, border="B", align="L")

            # 2. Type
            task_type = t.get("type", "—")
            if len(task_type) > 13:
                task_type = task_type[:12] + ".."
            pdf.set_fill_color(*row_bg)
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*COLORS["TEXT_DARK"])
            pdf.cell(COL_WIDTHS["type"], row_h, clean_pdf_text(task_type), fill=True, border="B", align="C")

            # 3. Owner
            owner = t.get("owner", "—")
            if len(owner) > 16:
                owner = owner[:15] + ".."
            pdf.set_fill_color(*row_bg)
            pdf.cell(COL_WIDTHS["owner"], row_h, clean_pdf_text(owner), fill=True, border="B", align="L")

            # 4. Planned Date
            target_d = t.get("planned_date") or t.get("target_date", "—") or "—"
            pdf.set_fill_color(*row_bg)
            pdf.cell(COL_WIDTHS["deadline"], row_h, clean_pdf_text(target_d), fill=True, border="B", align="C")

            # 5. Delay Days
            del_days = t.get("delay_days", 0)
            pdf.set_fill_color(*row_bg)
            if del_days > 0:
                pdf.set_font("Helvetica", "B", 7)
                pdf.set_text_color(*COLORS["RED"])
                pdf.cell(COL_WIDTHS["delay"], row_h, f"+{del_days}d", fill=True, border="B", align="C")
            else:
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(*COLORS["TEXT_GREY"])
                pdf.cell(COL_WIDTHS["delay"], row_h, clean_pdf_text("-"), fill=True, border="B", align="C")

            # 6. Progress (Visual Bar + %)
            x_prog = pdf.get_x()
            pdf.set_fill_color(*row_bg)
            pdf.cell(COL_WIDTHS["progress"], row_h, "", fill=True, border="B")

            prog_val = t.get("progress", 0)
            bar_w = 15
            bar_h = 2.2
            bar_x = x_prog + 3.5
            bar_y = y_row + 4.5

            # Background bar
            pdf.set_draw_color(*COLORS["LINE_GREY"])
            pdf.set_fill_color(230, 230, 230)
            pdf.rect(bar_x, bar_y, bar_w, bar_h, style="FD")

            # Fill bar
            p_color = COLORS["GREEN"] if prog_val >= 100 else COLORS["BLUE"]
            pdf.set_fill_color(*p_color)
            if prog_val > 0:
                pdf.rect(bar_x, bar_y, (prog_val / 100) * bar_w, bar_h, style="F")

            # Text %
            pdf.set_xy(x_prog, y_row + 0.8)
            pdf.set_font("Helvetica", "", 6)
            pdf.set_text_color(*COLORS["TEXT_GREY"])
            pdf.cell(COL_WIDTHS["progress"], 3, f"{prog_val}%", align="C")

            # 7. RAG Priority Badge
            pdf.set_xy(x_prog + COL_WIDTHS["progress"], y_row)
            rag_val = t.get("rag", "GREEN")
            rag_color = COLORS.get(rag_val, COLORS["TEXT_DARK"])

            x_rag = pdf.get_x()
            pdf.set_fill_color(*row_bg)
            pdf.cell(COL_WIDTHS["rag"], row_h, "", fill=True, border="B")

            # Small Dot indicator
            pdf.set_fill_color(*rag_color)
            pdf.ellipse(x_rag + 2, y_row + 3.5, 2, 2, style="F")

            # Label text
            pdf.set_xy(x_rag + 5, y_row)
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(*rag_color)
            pdf.cell(COL_WIDTHS["rag"] - 5, row_h, rag_val.capitalize(), align="L")

            # 8. Latest Note / Update
            pdf.set_xy(x_rag + COL_WIDTHS["rag"], y_row)
            note_str = t.get("latest_update") or "—"
            if len(note_str) > 13:
                note_str = note_str[:12] + ".."
            pdf.set_fill_color(*row_bg)
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*COLORS["TEXT_DARK"])
            pdf.cell(COL_WIDTHS["note"], row_h, clean_pdf_text(note_str), fill=True, border="B", align="L")

            # 9. Proof / Attachment Link
            proof_url = t.get("proof_url")
            pdf.set_fill_color(*row_bg)
            if proof_url:
                pdf.set_font("Helvetica", "U", 7)
                pdf.set_text_color(26, 115, 232)
                pdf.cell(COL_WIDTHS["proof"], row_h, "View", fill=True, border="B", align="C", link=proof_url)
            else:
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(*COLORS["TEXT_GREY"])
                pdf.cell(COL_WIDTHS["proof"], row_h, clean_pdf_text("-"), fill=True, border="B", align="C")

            pdf.ln(row_h)

        pdf.ln(3)

    # 4. Save and return filepath
    pdf.output(output_path)
    logger.info(f"Facilities EOD PDF successfully generated: {output_path} ({total_tasks} tasks)")
    return output_path


# ── Delivery & Messaging ─────────────────────────────────────────────────────

def send_facilities_eod_report(recipient_phone: str, send_summary_text: bool = True) -> bool:
    """
    Generate Facilities_Report_EOD.pdf and send it to the specified WhatsApp number.
    
    Args:
        recipient_phone: WhatsApp phone number (e.g. '917717754421')
        send_summary_text: If True, also sends a companion text summary
        
    Returns:
        True if successfully sent, False otherwise.
    """
    try:
        from whatsapp.task_assignment import _send_document_wa
        from whatsapp.ux import send_text

        # 1. Generate the PDF
        pdf_path = generate_facilities_eod_pdf()

        # 2. Send the PDF Document
        success = _send_document_wa(recipient_phone, pdf_path)
        if not success:
            logger.error(f"Failed to send Facilities PDF to {recipient_phone}")
            return False

        logger.info(f"Facilities_Report_EOD.pdf sent to {recipient_phone}")

        # 3. Optional companion text message
        if send_summary_text:
            tasks = fetch_live_facilities_tasks()
            total = len(tasks)
            red = sum(1 for t in tasks if t["rag"] == "RED")
            amber = sum(1 for t in tasks if t["rag"] == "AMBER")
            green = sum(1 for t in tasks if t["rag"] == "GREEN")
            completed = sum(1 for t in tasks if t["status"].lower() in ("closed", "completed", "done"))

            summary_msg = (
                f"📄 *Facilities EOD Report — {datetime.now().strftime('%d %b %Y')}*\n\n"
                f"📊 *Summary Overview:*\n"
                f"  • *Total Tasks:* {total}\n"
                f"  • 🔴 *Critical / Overdue:* {red}\n"
                f"  • 🟡 *Delayed / Due Today:* {amber}\n"
                f"  • 🟢 *On Track / Open:* {green}\n"
                f"  • ✅ *Completed:* {completed}\n\n"
                f"_The full report has been attached above as *Facilities_Report_EOD.pdf*._"
            )
            send_text(recipient_phone, summary_msg)

        return True

    except Exception as e:
        logger.error(f"Error in send_facilities_eod_report: {e}", exc_info=True)
        return False
