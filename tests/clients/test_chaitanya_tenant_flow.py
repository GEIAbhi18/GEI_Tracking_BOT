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
