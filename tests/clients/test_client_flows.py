from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from clients.flows import (
    handle_client_hi,
    handle_client_button_reply,
    handle_client_text,
    send_unregistered_client_message,
)
from clients.service import set_active_client_context, clear_client_context


@pytest.fixture(autouse=True)
def setup_test_clients(mocker):
    # Mock clients in service
    clients_data = [
        {
            "id": "c-1",
            "company_name": "HDFC Bank",
            "building": "GEBB1",
            "floor": "GROUND FLOOR",
            "unit_number": "R1/R2",
            "admin_name": "Rakesh Kumar",
            "mobile_number": "918826896085",
            "email": "rakesh@hdfcbank.in",
            "is_active": True,
        },
        {
            "id": "c-2a",
            "company_name": "Indus Insights",
            "building": "GEBB2",
            "floor": "2nd Floor",
            "unit_number": "201",
            "admin_name": "Mahesh",
            "mobile_number": "919958995715",
            "is_active": True,
        },
        {
            "id": "c-2b",
            "company_name": "Indus Insights",
            "building": "GEBB2",
            "floor": "10th Floor",
            "unit_number": "1001",
            "admin_name": "Mahesh",
            "mobile_number": "919958995715",
            "is_active": True,
        },
    ]

    mocker.patch("clients.flows.lookup_clients_by_phone", side_effect=lambda p: [
        c for c in clients_data if c["mobile_number"] == p or c["mobile_number"] == "91" + p
    ])
    mocker.patch("clients.service.lookup_clients_by_phone", side_effect=lambda p: [
        c for c in clients_data if c["mobile_number"] == p or c["mobile_number"] == "91" + p
    ])
    mock_sub = MagicMock()
    mock_sub.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mock_sub.upsert.return_value.execute.return_value = MagicMock(data=[])
    mocker.patch("clients.service.supabase.table", return_value=mock_sub)
    clear_client_context("918826896085")
    clear_client_context("919958995715")
    yield
    clear_client_context("918826896085")
    clear_client_context("919958995715")


def test_handle_client_hi_single_account(mocker):
    mock_list = mocker.patch("clients.flows.send_list_message")
    handle_client_hi("918826896085")

    mock_list.assert_called_once()
    args, kwargs = mock_list.call_args
    recipient = args[0]
    body = args[1]
    btn_text = args[2]
    sections = args[3]

    assert recipient == "918826896085"
    assert "HDFC Bank" in body
    assert "GEBB1" in body
    assert "R1/R2" in body
    assert btn_text == "Open Menu"
    assert len(sections) == 1
    rows = sections[0]["rows"]
    assert len(rows) == 4
    row_ids = [r["id"] for r in rows]
    assert "log_new_complaint" in row_ids
    assert "check_complaint_status" in row_ids
    assert "complaint_history" in row_ids
    assert "feedback_closed_complaints" in row_ids

    # Check labels
    assert any(r["title"] == "Check Status" for r in rows)
    assert any("Feedback" in r["title"] for r in rows)


def test_handle_client_hi_multi_account(mocker):
    mock_btn = mocker.patch("clients.flows.send_interactive_buttons")
    handle_client_hi("919958995715")

    mock_btn.assert_called_once()
    args = mock_btn.call_args[0]
    body = args[1]
    buttons = args[2]

    assert "multiple accounts" in body.lower()
    assert len(buttons) == 2
    assert buttons[0]["id"] == "client_sel_0"
    assert buttons[1]["id"] == "client_sel_1"


def test_handle_client_hi_unknown_number(mocker):
    mock_txt = mocker.patch("clients.flows.send_text")
    handle_client_hi("910000000000")

    mock_txt.assert_called_once()
    body = mock_txt.call_args[0][1]
    assert "couldn't find your details" in body.lower()


def test_handle_client_button_check_status(mocker):
    mocker.patch("clients.flows.send_text")
    mock_get = mocker.patch("clients.flows.get_complaints", return_value=[
        {
            "complaintId": "FT-101",
            "nature": "HVAC Cooling",
            "description": "3rd floor AC leak",
            "status": "In Progress",
            "createdAt": "2026-09-14",
        }
    ])

    handle_client_button_reply("918826896085", "check_complaint_status")
    mock_get.assert_called_once()


def test_handle_client_button_complaint_history(mocker):
    mocker.patch("clients.flows.send_text")
    mock_get = mocker.patch("clients.flows.get_complaints", return_value=[
        {
            "complaintId": "FT-99",
            "nature": "Electrical",
            "status": "Closed",
            "createdAt": "2026-08-01",
        }
    ])

    handle_client_button_reply("918826896085", "complaint_history")
    mock_get.assert_called_once()


def test_handle_client_button_log_new_complaint(mocker):
    mock_list = mocker.patch("clients.flows.send_list_message", return_value=True)
    handle_client_button_reply("918826896085", "log_new_complaint")

    mock_list.assert_called_once()
    args = mock_list.call_args[0]
    body = args[1]
    sections = args[3]
    assert "complaint nature" in body.lower()
    assert "HDFC Bank" in body
    assert len(sections[0]["rows"]) == 8


def test_complaint_logging_does_not_send_welcome_greeting(mocker):
    """Verifies that logging a complaint does NOT trigger the welcome greeting again."""
    mock_welcome = mocker.patch("clients.flows.send_client_welcome_menu")
    mock_post_opts = mocker.patch("clients.flows.send_post_complaint_options")
    mock_send_text = mocker.patch("clients.flows.send_text")
    mocker.patch("clients.flows.create_complaint", return_value={
        "success": True,
        "complaint_id": "GEI-9988",
        "message": "Complaint logged successfully",
    })

    # Mock state as awaiting description
    mock_state_res = MagicMock()
    mock_state_res.data = [{
        "action": "AWAITING_CLIENT_COMPLAINT_DESC",
        "metadata": {
            "client_context": {
                "company_name": "HDFC Bank",
                "building": "GEBB1",
                "unit_number": "R1/R2",
            }
        },
    }]
    mock_db = MagicMock()
    mock_db.select.return_value.eq.return_value.execute.return_value = mock_state_res
    mock_db.delete.return_value.eq.return_value.execute.return_value = MagicMock()
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)

    handled = handle_client_text("918826896085", "Water leaking from ceiling")
    assert handled is True

    # Critical requirement: greeting / welcome menu must NOT be triggered
    mock_welcome.assert_not_called()
    mock_post_opts.assert_called_once()


def test_update_complaint_button_single_active(mocker):
    """Verifies update complaint initiates prompt for single active complaint."""
    mock_send_text = mocker.patch("clients.flows.send_text")
    mocker.patch("clients.flows.get_complaints", return_value=[
        {
            "com_no": "GEI-1234",
            "complaintId": "GEI-1234",
            "nature": "Air Conditioning",
            "description": "AC unit cooling slow",
            "status": "In Progress",
        }
    ])

    mock_db = MagicMock()
    mock_upsert = MagicMock()
    mock_upsert.execute.return_value = MagicMock()
    mock_db.upsert.return_value = mock_upsert
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)

    handle_client_button_reply("918826896085", "update_complaint")

    mock_send_text.assert_called_once()
    prompt = mock_send_text.call_args[0][1]
    assert "GEI-1234" in prompt
    assert "Update Complaint" in prompt
    # Verifies state set to AWAITING_CLIENT_COMPLAINT_UPDATE
    assert mock_db.upsert.call_args[0][0]["action"] == "AWAITING_CLIENT_COMPLAINT_UPDATE"


def test_handle_client_text_update_flow(mocker):
    """Verifies client entering update text completes update without greeting."""
    mock_welcome = mocker.patch("clients.flows.send_client_welcome_menu")
    mock_post_opts = mocker.patch("clients.flows.send_post_complaint_options")
    mock_send_text = mocker.patch("clients.flows.send_text")
    mock_update = mocker.patch("clients.flows.update_complaint", return_value={
        "success": True,
        "complaint_id": "GEI-1234",
        "message": "Complaint updated successfully",
    })

    mock_state_res = MagicMock()
    mock_state_res.data = [{
        "action": "AWAITING_CLIENT_COMPLAINT_UPDATE",
        "metadata": {
            "client_context": {
                "company_name": "HDFC Bank",
                "building": "GEBB1",
                "unit_number": "R1/R2",
            },
            "target_complaint_id": "GEI-1234",
        },
    }]
    mock_db = MagicMock()
    mock_db.select.return_value.eq.return_value.execute.return_value = mock_state_res
    mock_db.delete.return_value.eq.return_value.execute.return_value = MagicMock()
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)

    handled = handle_client_text("918826896085", "Now also leaking water")
    assert handled is True

    mock_update.assert_called_once_with(
        {"company_name": "HDFC Bank", "building": "GEBB1", "unit_number": "R1/R2"},
        "GEI-1234",
        {"description": "Now also leaking water"}
    )
    mock_welcome.assert_not_called()
    mock_post_opts.assert_called_once()


def test_factech_update_complaint_api_call(mocker):
    """Verifies update_complaint in clients/factech_client sends PUT request and saves locally."""
    from clients.factech_client import update_complaint

    mock_put = mocker.patch("requests.put")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "success", "message": "Updated"}
    mock_put.return_value = mock_resp

    mock_db = MagicMock()
    mock_db.insert.return_value.execute.return_value = MagicMock()
    mocker.patch("db.supabase.table", return_value=mock_db)

    client = {
        "building": "GEBB2",
        "company_name": "Good Earth Infra (Dev Test)",
        "unit_number": "001",
        "mobile_number": "917717754421",
    }

    res = update_complaint(client, "GEI-14808", {"description": "Pantry tap still leaking"})
    assert res["success"] is True
    assert res["complaint_id"] == "GEI-14808"

    mock_put.assert_called_once()
    call_args = mock_put.call_args
    assert "593" in call_args[0][0]  # Site ID for GEBB2
    payload = call_args[1]["json"]
    assert payload["complaint_no"] == "GEI-14808"
    assert payload["description"] == "Pantry tap still leaking"

