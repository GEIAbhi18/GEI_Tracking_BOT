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
    mock_btn = mocker.patch("clients.flows.send_interactive_buttons")
    handle_client_hi("918826896085")

    mock_btn.assert_called_once()
    args, kwargs = mock_btn.call_args
    recipient = args[0]
    body = args[1]
    buttons = args[2]

    assert recipient == "918826896085"
    assert "HDFC Bank" in body
    assert "GEBB1" in body
    assert "R1/R2" in body
    assert len(buttons) == 3
    button_ids = [b["id"] for b in buttons]
    assert "log_new_complaint" in button_ids
    assert "check_complaint_status" in button_ids
    assert "complaint_history" in button_ids

    # Check button labels
    assert any(b["title"] == "Check Status" for b in buttons)


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
    mock_txt = mocker.patch("clients.flows.send_text")
    handle_client_button_reply("918826896085", "log_new_complaint")

    mock_txt.assert_called_once()
    body = mock_txt.call_args[0][1]
    assert "describe the issue" in body.lower()
    assert "HDFC Bank" in body
