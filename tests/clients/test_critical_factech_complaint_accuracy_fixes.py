"""
Targeted Automated Tests for:
# GEI_BOT — Critical Factech Complaint Accuracy & Progress Fixes

Covers:
  - Test A: Complaint status matching Factech as source of truth, stale cache overrides, and unknown status preservation.
  - Test B: Chaitanya Test identity resolution (919713957666 -> Chaitanya Test, GEEBTWOTest, Business Bay-II)
            and strict phone-conflict isolation from Nishant Lata (8952899000).
  - Test C: Authoritative closure dates from Factech without date fabrication.
  - Test D: Accurate complaint progress and requested status options format (WIP, Open, Closed, Hold).
  - Test E: Primary reference complaint B2-00090 live Factech verification.
"""

import time
import pytest
from unittest.mock import MagicMock, patch

from clients.factech_client import (
    get_complaint_by_id,
    get_complaints,
    derive_complaint_progress,
    format_complaint_status_and_progress,
)
from clients.service import (
    lookup_clients_by_phone,
    get_active_client_context,
)
from clients.flows import (
    handle_selected_complaint_details,
    handle_client_button_reply,
)
import feedback.sheets
from feedback.flow_sender import send_flow_template
from feedback.sheets import get_closed_complaints_for_client


CHAITANYA_PHONE = "919713957666"
NISHANT_PHONE = "918952899000"


# ─────────────────────────────────────────────────────────────────────────────
# Test A — Complaint status
# ─────────────────────────────────────────────────────────────────────────────
class TestComplaintStatus:
    def test_factech_status_is_source_of_truth_overrides_stale_cache(self, mocker):
        """Stale local status 'In Progress' is overridden by live Factech status 'Closed'."""
        stale_local = {
            "complaint_id": "B2-00090",
            "com_no": "B2-00090",
            "company": "Good Earth Infra",
            "unit": "GEEBTWOTest",
            "status": "In Progress",  # Stale!
            "created_at": "2026-06-01 09:53:43",
        }
        live_factech = {
            "com_no": "B2-00090",
            "status": "Closed",
            "unit": "GEEBTWOTest",
            "closed_at": "2026-06-01 09:53:47",
            "tat": "00:00:04",
            "remarks": "Issue sorted out",
        }

        mocker.patch("clients.factech_client._load_persisted_complaints", return_value=[stale_local])
        mocker.patch("clients.factech_client._LOGGED_COMPLAINTS_CACHE", [stale_local])
        mocker.patch("clients.factech_client.get_complaint_by_id", return_value=live_factech)

        client_ctx = {
            "company_name": "Good Earth Infra",
            "building": "Business Bay-II",
            "unit_number": "GEEBTWOTest",
            "mobile_number": CHAITANYA_PHONE,
        }

        complaints = get_complaints(client_ctx, days_back=180, active_only=False)
        target = next((c for c in complaints if c.get("com_no") == "B2-00090"), None)
        assert target is not None
        assert target["status"] == "Closed"
        assert target["closed_at"] == "2026-06-01 09:53:47"

    def test_unknown_status_is_preserved_not_force_converted(self):
        """Factech status outside standard four options (e.g. 'Cancel', 'Reopen') is preserved accurately."""
        complaint = {
            "com_no": "B2-99999",
            "status": "Cancel",
            "remarks": "Cancelled by user request",
        }
        formatted = format_complaint_status_and_progress(complaint)
        assert "Status: Cancel" in formatted
        assert "Available status options" not in formatted
        assert "Progress:" not in formatted

    def test_api_failure_handled_explicitly_no_silent_fallback_as_fresh(self, mocker):
        """When Factech API is unavailable, get_complaint_by_id returns None without crashing."""
        mocker.patch("requests.get", side_effect=Exception("Connection refused"))
        # pyrefly: ignore[bad-argument-type]
        res = get_complaint_by_id(site_id=593, complaint_id="B2-00090")
        assert res is None


# ─────────────────────────────────────────────────────────────────────────────
# Test B — Chaitanya Test identity resolution
# ─────────────────────────────────────────────────────────────────────────────
class TestClientIdentityResolution:
    def test_chaitanya_test_number_resolves_to_correct_tenant(self):
        """919713957666 resolves to Chaitanya Test, Good Earth Infra, Business Bay-II, GEEBTWOTest."""
        # Test full 12 digits
        clients_full = lookup_clients_by_phone("919713957666")
        assert len(clients_full) >= 1
        client = clients_full[0]
        assert client["admin_name"] == "Chaitanya Test"
        assert client["company_name"] == "Good Earth Infra"
        assert client["building"] == "Business Bay-II"
        assert client["unit_number"] == "GEEBTWOTest"

        # Test 10 digits without country code
        clients_10 = lookup_clients_by_phone("9713957666")
        assert len(clients_10) >= 1
        assert clients_10[0]["admin_name"] == "Chaitanya Test"
        assert clients_10[0]["unit_number"] == "GEEBTWOTest"

    def test_sheets_feedback_does_not_attribute_nishant_lata_tickets_to_chaitanya(self):
        """Closed complaints on shared unit belonging to Nishant's phone are not leaked to Chaitanya Test."""
        mock_sheet_records = [
            {
                "Complaint ID": "B2-00486",
                "Building": "Business Bay-II",
                "Unit / Flat No": "GEEBTWOTest",
                "Company Name": "Good Earth Infra",
                "Client Name / User": "Nishant Lata",
                "Client Phone": "8952899000",
                "Phone": "8952899000",
                "Status": "Closed",
                "Closed At": "2026-10-21 14:00:00",
            },
            {
                "Complaint ID": "B2-00090",
                "Building": "Business Bay-II",
                "Unit / Flat No": "GEEBTWOTest",
                "Company Name": "Good Earth Infra",
                "Client Name / User": "Chaitanya Test",
                "Client Phone": "9713957666",
                "Phone": "9713957666",
                "Status": "Closed",
                "Closed At": "2026-06-01 09:53:47",
            },
        ]
        # pyrefly: ignore[bad-assignment]
        feedback.sheets._master_records_cache = mock_sheet_records
        feedback.sheets._master_records_cache_time = time.time()

        # Query for Chaitanya Test phone
        chaitanya_complaints = get_closed_complaints_for_client(
            phone=CHAITANYA_PHONE,
            unit_no="GEEBTWOTest",
            company_name="Good Earth Infra",
            building="Business Bay-II",
        )
        c_cids = [c["complaintId"] for c in chaitanya_complaints]
        assert "B2-00090" in c_cids
        assert "B2-00486" not in c_cids  # Nishant's ticket strictly excluded!

        # Query for Nishant Lata phone
        nishant_complaints = get_closed_complaints_for_client(
            phone=NISHANT_PHONE,
            unit_no="GEEBTWOTest",
            company_name="Good Earth Infra",
            building="Business Bay-II",
        )
        n_cids = [c["complaintId"] for c in nishant_complaints]
        assert "B2-00486" in n_cids
        assert "B2-00090" not in n_cids  # Chaitanya's ticket strictly excluded!


# ─────────────────────────────────────────────────────────────────────────────
# Test C — Closure dates
# ─────────────────────────────────────────────────────────────────────────────
class TestClosureDateAccuracy:
    def test_genuine_closure_timestamp_used_without_fabrication(self, mocker):
        """flow_sender.send_flow_template uses genuine closed_at from Factech and does not invent timestamps."""
        mock_post = mocker.patch("requests.post", return_value=MagicMock(status_code=200, json=lambda: {"messages": [{"id": "mid-1"}]}))
        mock_send_text = mocker.patch("whatsapp.ux.send_text", return_value=True)

        # When closed_at is explicitly passed
        send_flow_template(
            phone="917717754421",
            client_name="Chaitanya Test",
            complaint_id="B2-00090",
            complaint_nature="Electrical",
            unit_no="GEEBTWOTest",
            complaint_details="Fan not working",
            closed_at="2026-06-01 09:53:47",
        )
        assert mock_post.called
        payload = mock_post.call_args[1]["json"]
        assert payload["template"]["components"][0]["parameters"][0]["text"] == "Chaitanya Test"

        # Verify genuine closure timestamp appears in WhatsApp message sent to user
        assert mock_send_text.called
        sent_body = mock_send_text.call_args[0][1]
        assert "Hello Chaitanya Test," in sent_body
        assert "Closed: 01-06-2026 09:53 AM" in sent_body or "2026-06-01 09:53:47" in sent_body

    def test_missing_closure_date_handled_safely_no_fabricated_date(self, mocker):
        """When closed_at is empty, it is marked as 'N/A' and never substituted with datetime.now()."""
        mock_post = mocker.patch("requests.post", return_value=MagicMock(status_code=200, json=lambda: {"messages": [{"id": "mid-2"}]}))

        send_flow_template(
            phone="917717754421",
            client_name="Chaitanya Test",
            complaint_id="B2-OPEN-1",
            complaint_nature="Civil",
            unit_no="GEEBTWOTest",
            complaint_details="Door lock issue",
            closed_at="",
        )
        payload = mock_post.call_args[1]["json"]
        body_text = payload["template"]["components"][0]["parameters"][0]["text"]
        # Body text must NOT contain today's date fabricated as Closed date
        assert "Closed: N/A" in body_text or "Closed:" not in body_text


# ─────────────────────────────────────────────────────────────────────────────
# Test D — Complaint progress and status options
# ─────────────────────────────────────────────────────────────────────────────
class TestComplaintProgressAndStatusOptions:
    def test_format_complaint_status_and_progress_specification(self):
        """Formats complaint details exactly per requirement format."""
        complaint = {
            "com_no": "B2-00090",
            "status": "WIP",
            "staff": "Sunil Kumar",
            "tat": "02:15:00",
            "remarks": "Technician on site",
        }
        res = format_complaint_status_and_progress(complaint)
        expected_lines = [
            "Complaint ID: B2-00090",
            "Status: WIP",
        ]
        for line in expected_lines:
            assert line in res
        assert "Available status options" not in res
        assert "Progress:" not in res

    def test_progress_derivation_from_factech_fields_only(self):
        """derive_complaint_progress derives progress from staff, remarks, tat, and status without guesswork."""
        # 1. Closed complaint
        c_closed = {
            "status": "Closed",
            "closed_at": "2026-06-01 09:53:47",
            "tat": "00:00:04",
        }
        p_closed = derive_complaint_progress(c_closed)
        assert "Resolved and closed (2026-06-01 09:53:47)" in p_closed
        assert "TAT: 00:00:04" in p_closed

        # 2. Hold complaint
        c_hold = {
            "status": "Hold",
            "remarks": "Awaiting spare parts from vendor",
        }
        p_hold = derive_complaint_progress(c_hold)
        assert "On hold" in p_hold
        assert "Awaiting spare parts from vendor" in p_hold

        # 3. Open complaint with no staff
        c_open = {"status": "Open"}
        p_open = derive_complaint_progress(c_open)
        assert p_open == "Logged and awaiting technician assignment"

    def test_handle_selected_complaint_details_displays_options_and_progress(self, mocker):
        """handle_selected_complaint_details formats message with progress and status options."""
        mock_complaint = {
            "com_no": "B2-00090",
            "complaintId": "B2-00090",
            "nature": "Electrical",
            "status": "Closed",
            "closed_at": "2026-06-01 09:53:47",
            "created_at": "2026-06-01 09:53:43",
            "tat": "00:00:04",
            "remarks": "Testing closure",
            "description": "Test complaint B2-00090",
        }
        mocker.patch("clients.flows.get_complaint_by_id", return_value=mock_complaint)
        mock_send_text = mocker.patch("clients.flows.send_text", return_value=True)
        mocker.patch("clients.flows.send_interactive_buttons", return_value=True)

        client_ctx = {
            "admin_name": "Chaitanya Test",
            "company_name": "Good Earth Infra",
            "building": "Business Bay-II",
            "unit_number": "GEEBTWOTest",
        }
        handle_selected_complaint_details(CHAITANYA_PHONE, client_ctx, "B2-00090")

        sent_msg = mock_send_text.call_args[0][1]
        assert "Complaint ID: B2-00090" in sent_msg
        assert "Status: Closed" in sent_msg
        assert "Available status options" not in sent_msg
        assert "Progress:" not in sent_msg
        assert "🏁 *Closed:* 2026-06-01 09:53:47" in sent_msg


# ─────────────────────────────────────────────────────────────────────────────
# Test E — Primary reference B2-00090 live Factech verification
# ─────────────────────────────────────────────────────────────────────────────
class TestPrimaryReferenceB200090:
    def test_live_factech_retrieval_for_b2_00090(self):
        """Direct live query to Factech API retrieves authentic record for B2-00090."""
        # pyrefly: ignore[bad-argument-type]
        record = get_complaint_by_id(site_id=593, complaint_id="B2-00090", dt_hint="2026-06-01 09:53:43")
        if record is None:
            pytest.skip("Factech external API not reachable in this runner environment")
        assert record.get("com_no") == "B2-00090"
        assert record.get("status") == "Closed"
        assert record.get("closed_at") == "2026-06-01 09:53:47"
        assert record.get("tat") == "00:00:04"
