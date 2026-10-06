"""
End-to-End and Integration tests for Factech Complaint Automation.

Tests verify:
1. Developer complaint flow:
   - Building: Business Bay-II
   - Site ID: 593
   - Unit No: GEEBTWOTest
   - Complaint Nature selection dropdown/list
   - Sub Nature selection dropdown/list
   - Description input
   - Factech API payload and Render logging verification

2. Chaitanya complaint flow:
   - Building: Business Bay-II
   - Site ID: 593
   - Unit No: GEEBTWOTest
   - Complaint Nature & Sub Nature selection
   - Description input
   - Factech API payload and Render logging verification

3. Normal tenant flow (Business Bay-I & Business Bay-II):
   - Tenant info read from GEI CLIENT ADMIN DETAILS Master Sheet
   - Site ID selected based on building (Bay-I -> 467, Bay-II -> 593)
   - Real unit number preserved (NEVER GEEBTWOTest)
   - Correct API payload and Render logging

4. Factech API Render logging format matches exact requirements.
"""
from __future__ import annotations
import json
import pytest
from unittest.mock import MagicMock, patch, call

from clients.config import (
    DEVELOPER_PHONE,
    CHAITANYA_PHONE,
    get_site_id_for_building,
    COMPLAINT_NATURES,
    SUB_NATURES_ALL,
)
from clients.factech_client import create_complaint
from clients.flows import (
    handle_client_text,
    handle_client_button_reply,
    prompt_complaint_nature_selection,
    prompt_complaint_sub_nature_selection,
    prompt_complaint_description,
)
from elara.team_router import set_active_team, clear_all_team_contexts


@pytest.fixture(autouse=True)
def cleanup():
    clear_all_team_contexts()
    yield
    clear_all_team_contexts()


# ── Test 1: Developer on Bay-II ──────────────────────────────────────────────

class TestDeveloperComplaintFlow:
    """Verifies Developer testing complaints on Business Bay-II only with unit GEEBTWOTest."""

    def test_developer_site_and_unit_mapping(self, mocker):
        """Developer context must use building Business Bay-II, Site ID 593, and Unit GEEBTWOTest."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "com_no": "B2-00455",
                "id": 2729783,
                "s_id": "593",
                "status": "Open",
            },
            "message": "Complaint added successfully",
        }
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        dev_context = {
            "admin_name": "Abhijeet (Developer)",
            "company_name": "Good Earth Infra (Dev Test)",
            "mobile_number": DEVELOPER_PHONE,
            "building": "Business Bay-II",
            "unit_number": "GEEBTWOTest",
        }

        complaint_data = {
            "nature": "Electrical",
            "sub_nature": "Others",
            "description": "Testing complaint from Thunder Client",
            "reference_no": "GEIBOT001",
        }

        result = create_complaint(dev_context, complaint_data)

        assert result["success"] is True
        assert result["complaint_id"] == "B2-00455"

        mock_post.assert_called_once()
        called_url = mock_post.call_args[0][0]
        payload = mock_post.call_args[1]["json"]

        # 1. URL must use site 593
        assert "/v1/thirdparty/site/593/complaint" in called_url

        # 2. Payload must use GEEBTWOTest
        assert payload["unit_no"] == "GEEBTWOTest"
        assert payload["category"] == "Electrical"
        assert payload["sub_category"] == "Others"
        assert payload["description"] == "Testing complaint from Thunder Client"
        assert payload["reference_no"] == "GEIBOT001"

    def test_developer_end_to_end_whatsapp_flow(self, mocker, capsys):
        """
        Developer initiates 'Log New Complaint' -> selects Nature -> selects Sub Nature ->
        provides Description -> receives confirmation with Complaint ID.
        """
        set_active_team(DEVELOPER_PHONE, "factech")

        mock_send_list = mocker.patch("clients.flows.send_list_message", return_value=True)
        mock_send_text = mocker.patch("clients.flows.send_text", return_value=True)
        mocker.patch("clients.flows.send_post_complaint_options")

        # Mock Factech API response
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "com_no": "B2-00455",
                "id": 2729783,
                "s_id": "593",
                "status": "Open",
            },
            "message": "Complaint added successfully",
        }
        mock_post.return_value = mock_resp

        # Mock Supabase wa_task_states
        state_store = {}

        def mock_supabase_table(table_name):
            mock_table = MagicMock()
            if table_name == "wa_task_states":
                def mock_upsert(data, **kwargs):
                    state_store[data["whatsapp_number"]] = data
                    res = MagicMock()
                    res.execute.return_value = MagicMock(data=[data])
                    return res
                def mock_select(*args):
                    sel = MagicMock()
                    def mock_eq(col, val):
                        exec_mock = MagicMock()
                        stored = state_store.get(val)
                        exec_mock.execute.return_value = MagicMock(data=[stored] if stored else [])
                        return exec_mock
                    sel.eq = mock_eq
                    return sel
                def mock_delete():
                    del_mock = MagicMock()
                    def mock_eq(col, val):
                        state_store.pop(val, None)
                        exec_mock = MagicMock()
                        exec_mock.execute.return_value = MagicMock(data=[])
                        return exec_mock
                    del_mock.eq = mock_eq
                    return del_mock
                mock_table.upsert = mock_upsert
                mock_table.select = mock_select
                mock_table.delete = mock_delete
            return mock_table

        mocker.patch("clients.flows.supabase.table", side_effect=mock_supabase_table)
        mocker.patch("db.supabase.table", side_effect=mock_supabase_table)

        # Step 1: Developer clicks 'Log New Complaint'
        handle_client_button_reply(DEVELOPER_PHONE, "log_new_complaint")

        # Must have sent list message with 8 complaint nature options
        assert mock_send_list.call_count == 1
        args = mock_send_list.call_args[0]
        assert "select the *complaint nature*" in args[1].lower()
        nature_rows = args[3][0]["rows"]
        assert len(nature_rows) == 8
        nature_titles = [r["title"] for r in nature_rows]
        assert "Electrical" in nature_titles
        assert "Civil" in nature_titles

        # Step 2: Developer selects 'Electrical' (c_nat_1)
        handle_client_button_reply(DEVELOPER_PHONE, "c_nat_1")

        # Must have sent list message for Electrical sub natures
        assert mock_send_list.call_count == 2
        args2 = mock_send_list.call_args[0]
        assert "select the *sub nature*" in args2[1].lower()
        sub_rows = args2[3][0]["rows"]
        sub_titles = [r["title"] for r in sub_rows]
        assert "Power Failure" in sub_titles
        assert "Others" in sub_titles or "Other" in sub_titles

        # Step 3: Developer selects Sub Nature 'Power Failure' via text or button
        handle_client_text(DEVELOPER_PHONE, "Power Failure")

        # Must have prompted for complaint description
        assert mock_send_text.call_count >= 1
        desc_prompt = mock_send_text.call_args_list[-1][0][1]
        assert "please describe the issue" in desc_prompt.lower()
        assert "Electrical" in desc_prompt
        assert "Power Failure" in desc_prompt

        # Step 4: Developer enters description
        handle_client_text(DEVELOPER_PHONE, "Main switch tripping repeatedly on floor")

        # Verify API request payload sent to Factech
        mock_post.assert_called_once()
        called_url = mock_post.call_args[0][0]
        payload = mock_post.call_args[1]["json"]

        assert "/v1/thirdparty/site/593/complaint" in called_url
        assert payload["unit_no"] == "GEEBTWOTest"
        assert payload["category"] == "Electrical"
        assert payload["sub_category"] == "Power Failure"
        assert payload["description"] == "Main switch tripping repeatedly on floor"

        # Verify confirmation message to user
        final_msg = mock_send_text.call_args_list[-1][0][1]
        assert "Complaint Logged Successfully" in final_msg
        assert "#B2-00455" in final_msg
        assert "Business Bay-II" in final_msg
        assert "GEEBTWOTest" in final_msg


# ── Test 2: Chaitanya on Bay-II ──────────────────────────────────────────────

class TestChaitanyaComplaintFlow:
    """Verifies Chaitanya testing complaints on Business Bay-II only with unit GEEBTWOTest."""

    def test_chaitanya_site_and_unit_mapping(self, mocker):
        """Chaitanya context must use building Business Bay-II, Site ID 593, and Unit GEEBTWOTest."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "com_no": "B2-00456",
                "id": 2729784,
                "s_id": "593",
                "status": "Open",
            },
            "message": "Complaint added successfully",
        }
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        chaitanya_context = {
            "admin_name": "Chaitanya Test",
            "company_name": "Good Earth Infra",
            "mobile_number": CHAITANYA_PHONE,
            "building": "Business Bay-II",
            "unit_number": "GEEBTWOTest",
        }

        complaint_data = {
            "nature": "HVAC",
            "sub_nature": "AC not working",
            "description": "AC unit stopped blowing cold air",
        }

        result = create_complaint(chaitanya_context, complaint_data)

        assert result["success"] is True
        assert result["complaint_id"] == "B2-00456"

        mock_post.assert_called_once()
        called_url = mock_post.call_args[0][0]
        payload = mock_post.call_args[1]["json"]

        assert "/v1/thirdparty/site/593/complaint" in called_url
        assert payload["unit_no"] == "GEEBTWOTest"
        assert payload["category"] == "HVAC"
        assert payload["sub_category"] == "AC not working"
        assert payload["description"] == "AC unit stopped blowing cold air"


# ── Test 3: Normal Tenant ────────────────────────────────────────────────────

class TestNormalTenantComplaintFlow:
    """Verifies normal tenants have building/unit read from Master Sheet and use correct Site IDs."""

    def test_normal_tenant_bay1_uses_site_467_and_sheet_unit(self, mocker):
        """Normal tenant in Business Bay-I uses Site ID 467 and their real sheet unit number."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "com_no": "B1-00123",
                "id": 100123,
                "s_id": "467",
                "status": "Open",
            },
            "message": "Complaint added successfully",
        }
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        # Tenant from Master sheet (HDFC Bank, Ground Floor, R1/R2, GEBB I)
        tenant_context = {
            "admin_name": "Rakesh Kumar",
            "company_name": "HDFC Bank",
            "building": "GEBB I",
            "floor": "GROUND FLOOR",
            "unit_number": "R1/R2",
            "mobile_number": "918826896085",
            "email": "rakesh.kumar125@hdfcbank.in",
        }

        complaint_data = {
            "nature": "Plumbing",
            "sub_nature": "Tap Not Working",
            "description": "Washroom tap dripping continuously",
        }

        result = create_complaint(tenant_context, complaint_data)

        assert result["success"] is True
        assert result["complaint_id"] == "B1-00123"

        mock_post.assert_called_once()
        called_url = mock_post.call_args[0][0]
        payload = mock_post.call_args[1]["json"]

        # 1. URL must use site 467 for Business Bay-I
        assert "/v1/thirdparty/site/467/complaint" in called_url

        # 2. Unit must be the sheet unit R1/R2 (NOT GEEBTWOTest)
        assert payload["unit_no"] == "R1/R2"
        assert payload["unit_no"] != "GEEBTWOTest"
        assert payload["category"] == "Plumbing"
        assert payload["sub_category"] == "Tap Not Working"

    def test_normal_tenant_bay2_uses_site_593_and_sheet_unit(self, mocker):
        """Normal tenant in Business Bay-II uses Site ID 593 and their real sheet unit number."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "com_no": "B2-00999",
                "id": 200999,
                "s_id": "593",
                "status": "Open",
            },
            "message": "Complaint added successfully",
        }
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        # Normal tenant in Bay-II
        tenant_context = {
            "admin_name": "Normal User",
            "company_name": "Acme Corp",
            "building": "Business Bay-II",
            "floor": "5th Floor",
            "unit_number": "504",
            "mobile_number": "919988776655",
            "email": "admin@acme.com",
        }

        complaint_data = {
            "nature": "Civil",
            "sub_nature": "Floor Tiles/Marble Broken/Damaged",
            "description": "Broken tiles in entrance corridor",
        }

        result = create_complaint(tenant_context, complaint_data)

        assert result["success"] is True
        assert result["complaint_id"] == "B2-00999"

        mock_post.assert_called_once()
        called_url = mock_post.call_args[0][0]
        payload = mock_post.call_args[1]["json"]

        # Site 593 for Business Bay-II
        assert "/v1/thirdparty/site/593/complaint" in called_url
        # Sheet unit number preserved (NOT GEEBTWOTest)
        assert payload["unit_no"] == "504"
        assert payload["unit_no"] != "GEEBTWOTest"
        assert payload["category"] == "Civil"
        assert payload["sub_category"] == "Floor Tiles/Marble Broken/Damaged"


# ── Test 4: Render Logging Verification ──────────────────────────────────────

class TestRenderLogging:
    """Verifies clear Render logs around every Factech complaint API request and response."""

    def test_render_logs_on_success(self, mocker, capsys):
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {"com_no": "B2-00455", "id": 2729783},
            "message": "Complaint added successfully",
        }
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        client = {
            "admin_name": "Abhijeet (Developer)",
            "company_name": "Good Earth Infra (Dev Test)",
            "mobile_number": DEVELOPER_PHONE,
            "building": "Business Bay-II",
            "unit_number": "GEEBTWOTest",
        }
        create_complaint(client, {
            "nature": "Electrical",
            "sub_nature": "Others",
            "description": "Testing Render logs",
        })

        captured = capsys.readouterr().out

        # Must include FACTECH COMPLAINT REQUEST block
        assert "FACTECH COMPLAINT REQUEST" in captured
        assert "Site ID: 593" in captured
        assert "Building: Business Bay-II" in captured
        assert "Unit No: GEEBTWOTest" in captured
        assert "Complaint Nature: Electrical" in captured
        assert "Sub Nature: Others" in captured
        assert "Description: Testing Render logs" in captured
        assert "API URL: https://api.isocietymanager.com/v1/thirdparty/site/593/complaint" in captured
        assert "Request Payload:" in captured

        # Must include FACTECH COMPLAINT RESPONSE block
        assert "FACTECH COMPLAINT RESPONSE" in captured
        assert "HTTP Status: 200" in captured
        assert "B2-00455" in captured

    def test_render_logs_on_api_error(self, mocker, capsys):
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "status": "error",
            "message": "Unit not found in site 593",
        }
        mock_resp.headers = {}
        mock_resp.text = '{"status":"error","message":"Unit not found in site 593"}'
        mock_post.return_value = mock_resp

        client = {
            "admin_name": "Abhijeet (Developer)",
            "company_name": "Good Earth Infra (Dev Test)",
            "mobile_number": DEVELOPER_PHONE,
            "building": "Business Bay-II",
            "unit_number": "GEEBTWOTest",
        }
        create_complaint(client, {
            "nature": "Electrical",
            "sub_nature": "Others",
            "description": "Testing error logs",
        })

        captured = capsys.readouterr().out

        # Must include FACTECH COMPLAINT API ERROR block
        assert "FACTECH COMPLAINT API ERROR" in captured
        assert "HTTP Status: 400" in captured
        assert "Unit not found in site 593" in captured
