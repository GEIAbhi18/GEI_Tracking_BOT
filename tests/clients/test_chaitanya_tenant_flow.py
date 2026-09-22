from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from clients.config import (
    TREAT_CHAITANYA_AS_TENANT_ONLY,
    CHAITANYA_PHONE,
    CHAITANYA_ALT_PHONE,
    CHAITANYA_USER_ID,
    CHAITANYA_TENANT_RECORD,
    is_chaitanya,
)
from clients.service import lookup_clients_by_phone, get_active_client_context
from clients.flows import is_registered_client, handle_client_hi
from auth.middleware import authenticate_whatsapp_request
from auth.permissions import Role, Permission
from whatsapp.menus import send_main_menu


def test_is_chaitanya_helper():
    assert is_chaitanya(CHAITANYA_PHONE) is True
    assert is_chaitanya(CHAITANYA_ALT_PHONE) is True
    assert is_chaitanya("+919713957666") is True
    assert is_chaitanya(CHAITANYA_USER_ID) is True
    assert is_chaitanya("Chaitanya") is True
    assert is_chaitanya("Chaitnaya") is True
    assert is_chaitanya("9999999999") is False
    assert is_chaitanya("Kanav") is False


def test_lookup_clients_for_chaitanya():
    # Test both standard 12-digit and 10-digit variants
    clients = lookup_clients_by_phone(CHAITANYA_PHONE)
    assert len(clients) == 1
    c = clients[0]
    assert c["company_name"] == "Good Earth Infra"
    assert c["building"] == "GEBB2"
    assert c["unit_number"] == "1"
    assert c["admin_name"] == "Chaitanya Test"

    clients_alt = lookup_clients_by_phone(CHAITANYA_ALT_PHONE)
    assert len(clients_alt) == 1
    assert clients_alt[0]["admin_name"] == "Chaitanya Test"

    assert is_registered_client(CHAITANYA_PHONE) is True
    assert is_registered_client(CHAITANYA_ALT_PHONE) is True


def test_get_active_client_context_defaults_to_chaitanya_record():
    ctx = get_active_client_context(CHAITANYA_PHONE)
    assert ctx is not None
    assert ctx["company_name"] == "Good Earth Infra"
    assert ctx["unit_number"] == "1"


def test_auth_middleware_treats_chaitanya_as_client_only(mocker):
    # Mock DB user row representing Chaitanya
    mock_db_user = {
        "id": CHAITANYA_USER_ID,
        "name": "Chaitanya",
        "role": "Employee",
        "whatsapp_number": CHAITANYA_PHONE,
        "department": "Tech",
        "team_id": "team-123",
        "permitted_buildings": ["GEBB1"],
    }
    mocker.patch("auth.middleware.get_or_create_user_by_whatsapp", return_value=dict(mock_db_user))

    user = authenticate_whatsapp_request(CHAITANYA_PHONE)
    assert user is not None
    # Must be Client, NOT Employee
    assert user["role"] == Role.CLIENT.value
    assert user["department"] is None
    assert user["team_id"] is None
    assert user["permitted_buildings"] == []
    # Permissions must only include Client permissions
    assert Permission.ACCESS_COMPLAINTS in user["permissions"]
    assert Permission.CREATE_TEAM_TASKS not in user["permissions"]
    assert Permission.VIEW_OWN_TEAM_TASKS not in user["permissions"]


def test_send_main_menu_routes_chaitanya_to_factech_menu(mocker):
    mock_buttons = mocker.patch("clients.flows.send_interactive_buttons", return_value=True)
    mock_list = mocker.patch("whatsapp.ux.send_list_message", return_value=True)

    user = {"role": "Client", "name": "Chaitanya", "whatsapp_number": CHAITANYA_PHONE}
    send_main_menu(CHAITANYA_PHONE, user)

    # Must NOT send the team tasks list menu
    mock_list.assert_not_called()

    # Must send Factech 3-button welcome card
    mock_buttons.assert_called_once()
    args, kwargs = mock_buttons.call_args
    target_to, body, buttons = args[0], args[1], args[2]

    assert target_to == CHAITANYA_PHONE
    assert "Good Earth Infra" in body
    assert "*Unit:* 1" in body
    assert len(buttons) == 3
    button_ids = [b["id"] for b in buttons]
    assert "log_new_complaint" in button_ids
    assert "check_complaint_status" in button_ids
    assert "complaint_history" in button_ids


def test_team_task_assignment_excludes_chaitanya(mocker):
    from whatsapp.handlers import send_assignee_selection_prompt

    users_db = [
        {"id": "u-1", "name": "Kanav", "role": "Director", "whatsapp_number": "919999999999"},
        {"id": "u-2", "name": "Anoop", "role": "Employee", "whatsapp_number": "918888888888"},
        {"id": CHAITANYA_USER_ID, "name": "Chaitanya", "role": "Client", "whatsapp_number": CHAITANYA_PHONE},
    ]

    mock_table = MagicMock()
    mock_table.select.return_value.execute.return_value = MagicMock(data=users_db)
    mocker.patch("db.supabase.table", return_value=mock_table)
    mock_buttons = mocker.patch("whatsapp.ux.send_interactive_buttons", return_value=True)

    send_assignee_selection_prompt("919999999999", "task-1", "Test Project Task", {"id": "u-1"})


    mock_buttons.assert_called_once()
    buttons = mock_buttons.call_args[0][2]
    button_titles = [b["title"] for b in buttons]

    # Kanav and Anoop present, Chaitanya MUST be excluded
    assert "Kanav" in button_titles
    assert "Anoop" in button_titles
    assert "Chaitanya" not in button_titles




def test_elara_team_router_bypasses_chaitanya():
    from elara.team_router import route_incoming_message

    # Team router should immediately return False for Chaitanya
    handled = route_incoming_message(CHAITANYA_PHONE, text="hi")
    assert handled is False


def test_send_client_welcome_menu_fallback_on_button_failure(mocker):
    from clients.flows import send_client_welcome_menu

    # Simulate interactive buttons failing (e.g. Meta limitation or network error)
    mocker.patch("clients.flows.send_interactive_buttons", return_value=False)
    mock_text = mocker.patch("clients.flows.send_text", return_value=True)

    client = {
        "admin_name": "Chaitanya Test",
        "company_name": "Good Earth Infra",
        "building": "GEBB2",
        "unit_number": "1",
    }
    send_client_welcome_menu(CHAITANYA_PHONE, client)

    mock_text.assert_called_once()
    sent_content = mock_text.call_args[0][1]
    assert "1️⃣ *Log New Complaint*" in sent_content
    assert "2️⃣ *Check Status*" in sent_content
    assert "3️⃣ *Complaint History*" in sent_content


def test_factech_create_complaint_pads_short_unit(mocker):
    from clients.factech_client import create_complaint

    mock_post = mocker.patch("requests.post")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "success", "complaintId": "FT-9999"}
    mock_post.return_value = mock_resp

    client = {
        "admin_name": "Chaitanya",
        "company_name": "Good Earth Infra",
        "building": "GEBB2",
        "unit_number": "1",
        "mobile_number": CHAITANYA_PHONE,
        "email": "",
        "floor": "Ground",
    }
    res = create_complaint(client, {"nature": "AC", "description": "AC not cooling"})

    assert res["success"] is True
    assert res["complaint_id"] == "FT-9999"

    # Verify payload had padded unit number (>= 3 chars)
    payload = mock_post.call_args[1]["json"]
    assert payload["unit_no"] == "001"


def test_factech_create_complaint_resilient_fallback_on_api_error(mocker):
    from clients.factech_client import create_complaint

    # Simulate Factech returning site error: unit not found
    mock_post = mocker.patch("requests.post")
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "Unit not found in site"
    mock_resp.json.return_value = {"status": "error", "message": "Unit not found in site"}
    mock_post.return_value = mock_resp

    mock_insert = MagicMock()
    mock_insert.execute.return_value = MagicMock(data=[])
    mock_table = MagicMock()
    mock_table.insert.return_value = mock_insert
    mocker.patch("db.supabase.table", return_value=mock_table)

    client = {
        "admin_name": "Chaitanya",
        "company_name": "Good Earth Infra",
        "building": "GEBB2",
        "unit_number": "1",
        "mobile_number": CHAITANYA_PHONE,
    }
    res = create_complaint(client, {"nature": "AC", "description": "AC not cooling"})

    assert res["success"] is True
    assert res["fallback"] is True
    assert res["complaint_id"].startswith("GEI-")


def test_get_complaints_strict_unit_matching_prevents_leakage(mocker):
    from clients.factech_client import get_complaints

    # Raw complaints from site including unit 101, 201, 1 (exact), and Shop 1
    raw_api_complaints = [
        {"com_no": "C-101", "unitNo": "101", "status": "Open"},
        {"com_no": "C-201", "unitNo": "201", "status": "Open"},
        {"com_no": "C-1", "unitNo": "1", "status": "Open"},
        {"com_no": "C-001", "unitNo": "001", "status": "Open"},
        {"com_no": "C-601", "unitNo": "601", "status": "Open"},
    ]
    mock_get = mocker.patch("requests.get")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"objects": raw_api_complaints}
    mock_get.return_value = mock_resp

    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    mocker.patch("db.supabase.table", return_value=mock_table)

    client = {"building": "GEBB2", "unit_number": "1", "mobile_number": CHAITANYA_PHONE}
    results = get_complaints(client, days_back=30)

    matched_ids = [c["com_no"] for c in results]
    # Only exact unit 1 and 001 should match; 101, 201, 601 must NOT match
    assert "C-1" in matched_ids
    assert "C-001" in matched_ids
    assert "C-101" not in matched_ids
    assert "C-201" not in matched_ids
    assert "C-601" not in matched_ids


def test_webhook_client_text_routing(mocker):
    from whatsapp.whatsapp_webhook import _handle_text

    mock_btn_reply = mocker.patch("clients.flows.handle_client_button_reply")
    mock_client_hi = mocker.patch("clients.flows.handle_client_hi")

    # 1 -> log_new_complaint
    _handle_text(CHAITANYA_PHONE, "1")
    mock_btn_reply.assert_called_with(CHAITANYA_PHONE, "log_new_complaint")

    # 2 -> check_complaint_status
    _handle_text(CHAITANYA_PHONE, "2")
    mock_btn_reply.assert_called_with(CHAITANYA_PHONE, "check_complaint_status")

    # 3 -> complaint_history
    _handle_text(CHAITANYA_PHONE, "3")
    mock_btn_reply.assert_called_with(CHAITANYA_PHONE, "complaint_history")

    # greeting with punctuation e.g. "Hello!"
    _handle_text(CHAITANYA_PHONE, "Hello!")
    mock_client_hi.assert_called_with(CHAITANYA_PHONE)

    # arbitrary unrouted text -> shows client menu
    _handle_text(CHAITANYA_PHONE, "What are the facilities here?")
    mock_client_hi.assert_called_with(CHAITANYA_PHONE)

