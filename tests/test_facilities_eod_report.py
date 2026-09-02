"""
Tests for Facilities EOD Report Generation, Delivery, and WhatsApp Routing.
===========================================================================
"""

import os
import pytest
from datetime import date, datetime
from unittest.mock import patch, MagicMock

from facilities.eod_report import (
    calculate_task_rag,
    calculate_task_progress,
    clean_pdf_text,
    generate_facilities_eod_pdf,
    fetch_live_facilities_tasks,
    send_facilities_eod_report,
)


class TestFacilitiesEODReportRAG:
    """Test RAG and delay calculations for Facilities tasks."""

    def test_completed_task_is_green(self):
        task = {"status": "Closed", "target_date": "10-Aug-2026", "delay_days": 5}
        rag, delay = calculate_task_rag(task, today_date=date(2026, 8, 31))
        assert rag == "GREEN"
        assert delay == 0

    def test_overdue_task_is_red(self):
        task = {"status": "Open", "target_date": "20-Aug-2026", "delay_days": 0}
        rag, delay = calculate_task_rag(task, today_date=date(2026, 8, 31))
        assert rag == "RED"
        assert delay == 11

    def test_explicit_delay_days_is_red(self):
        task = {"status": "WIP", "target_date": "31-Aug-2026", "delay_days": 3}
        rag, delay = calculate_task_rag(task, today_date=date(2026, 8, 31))
        assert rag == "RED"
        assert delay == 3

    def test_due_today_task_is_amber(self):
        task = {"status": "Open", "target_date": "31-Aug-2026", "delay_days": 0}
        rag, delay = calculate_task_rag(task, today_date=date(2026, 8, 31))
        assert rag == "AMBER"
        assert delay == 0

    def test_task_with_blocker_is_amber(self):
        task = {"status": "Open", "target_date": "15-Sep-2026", "blocker": "Waiting for vendor spare parts"}
        rag, delay = calculate_task_rag(task, today_date=date(2026, 8, 31))
        assert rag == "AMBER"
        assert delay == 0

    def test_future_task_without_blocker_is_green(self):
        task = {"status": "Open", "target_date": "15-Sep-2026", "blocker": "None"}
        rag, delay = calculate_task_rag(task, today_date=date(2026, 8, 31))
        assert rag == "GREEN"
        assert delay == 0


class TestFacilitiesEODProgress:
    """Test progress derivation from task status."""

    def test_closed_task_progress(self):
        assert calculate_task_progress({"status": "Closed"}) == 100
        assert calculate_task_progress({"status": "Completed"}) == 100

    def test_wip_task_progress(self):
        assert calculate_task_progress({"status": "WIP"}) == 50

    def test_explicit_progress(self):
        assert calculate_task_progress({"status": "WIP", "progress": "75%"}) == 75
        assert calculate_task_progress({"status": "Open", "progress": 30}) == 30


class TestFacilitiesPDFGeneration:
    """Test PDF generation mechanics."""

    def test_generate_pdf_creates_valid_file(self, tmp_path):
        sample_tasks = [
            {
                "ref_no": "GEBB1-001",
                "building": "GEBB1",
                "type": "Project",
                "issue_action": "Centric leakage repair on 9th floor",
                "latest_update": "Work ongoing",
                "added_by": "Facilities Director",
                "owner": "Facility Manager",
                "created_date": "10-Aug-2026",
                "target_date": "20-Aug-2026",
                "delay_days": 11,
                "status": "WIP",
                "rag": "RED",
                "progress": 50,
                "blocker": "Material delay",
                "proof_url": "https://example.com/proof.jpg",
            },
            {
                "ref_no": "GETT-002",
                "building": "GETT",
                "type": "Major Concern",
                "issue_action": "Fire alarm sensor check",
                "latest_update": "Inspected and resolved",
                "added_by": "Facilities Director",
                "owner": "Facility Head",
                "created_date": "25-Aug-2026",
                "target_date": "30-Aug-2026",
                "delay_days": 0,
                "status": "Closed",
                "rag": "GREEN",
                "progress": 100,
                "blocker": "—",
                "proof_url": None,
            }
        ]

        out_pdf = str(tmp_path / "Facilities_Report_EOD.pdf")
        result_path = generate_facilities_eod_pdf(tasks=sample_tasks, output_path=out_pdf)

        assert os.path.exists(result_path)
        assert result_path.endswith("Facilities_Report_EOD.pdf")
        assert os.path.getsize(result_path) > 1000  # Non-trivial PDF size

    def test_clean_pdf_text_encodes_safely(self):
        assert clean_pdf_text("Task — with em-dash & quotes “smart”") == "Task - with em-dash & quotes \"smart\""
        assert clean_pdf_text(None) == "-"


class TestFacilitiesDeliveryAndRouting:
    """Test on-demand triggers and delivery to WhatsApp."""

    @patch("whatsapp.task_assignment._send_document_wa", return_value=True)
    @patch("whatsapp.ux.send_text")
    def test_send_facilities_eod_report_calls_whatsapp(self, mock_send_text, mock_send_doc):
        sample_tasks = [{"ref_no": "GEBB1-001", "building": "GEBB1", "status": "Open", "rag": "GREEN"}]
        with patch("facilities.eod_report.fetch_live_facilities_tasks", return_value=sample_tasks):
            success = send_facilities_eod_report("917717754421", send_summary_text=True)
            assert success is True
            assert mock_send_doc.called
            assert mock_send_text.called
            # Verify document name
            doc_path = mock_send_doc.call_args[0][1]
            assert "Facilities_Report_EOD.pdf" in doc_path

    @patch("facilities.eod_report.send_facilities_eod_report", return_value=True)
    @patch("whatsapp.ux.send_text")
    def test_router_handles_facilities_report_query(self, mock_send_text, mock_send_report):
        from facilities.flows.router import _route_text

        sender = "917717754421"
        user = {
            "name": "Kanav",
            "role": "Director",
            "department": "Facilities",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        queries = [
            "facilities report",
            "Facilitite Report",
            "facility report",
            "Facilities EOD Report",
            "eod report",
        ]

        for q in queries:
            mock_send_report.reset_mock()
            _route_text(sender, q, user, session=None)
            assert mock_send_report.called, f"Failed for query: {q}"
            assert mock_send_report.call_args[0][0] == sender

    @patch("facilities.eod_report.send_facilities_eod_report", return_value=True)
    @patch("db.supabase")
    def test_whatsapp_daily_report_job_sends_facilities_pdf(self, mock_sb, mock_send_report):
        from whatsapp.whatsapp_webhook import whatsapp_daily_report_job

        # Mock Kanav user lookup
        mock_user_res = MagicMock()
        mock_user_res.data = [{"whatsapp_number": "917717754421"}]
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_user_res
        mock_sb.table.return_value.select.return_value.gte.return_value.execute.return_value = MagicMock(data=[])

        whatsapp_daily_report_job()
        assert mock_send_report.called
        assert mock_send_report.call_args[0][0] == "917717754421"
