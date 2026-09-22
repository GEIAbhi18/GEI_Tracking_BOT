from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock

from elara.config import DEVELOPER_PHONE, KANAV_PHONE
from clients.config import DEVELOPER_TENANT_RECORD, is_developer_phone
from clients.service import lookup_clients_by_phone, get_active_client_context
from elara.team_router import (
    send_team_selection_prompt,
    route_incoming_message,
    set_active_team,
    get_active_team,
)


def test_is_developer_phone_helper():
    assert is_developer_phone(DEVELOPER_PHONE) is True
    assert is_developer_phone("+917717754421") is True
    assert is_developer_phone("7717754421") is True
    assert is_developer_phone(KANAV_PHONE) is False
    assert is_developer_phone("9999999999") is False


def test_team_selection_prompt_includes_factech_for_developer(mocker):
    mock_buttons = mocker.patch("elara.team_router.send_interactive_buttons", return_value=True)

    send_team_selection_prompt(DEVELOPER_PHONE)

    mock_buttons.assert_called_once()
    buttons = mock_buttons.call_args[0][2]
    button_ids = [b["id"] for b in buttons]

    assert "team_sel_facilities" in button_ids
    assert "team_sel_elara" in button_ids
    assert "team_sel_factech" in button_ids
    assert len(buttons) == 3


def test_team_selection_prompt_for_kanav_keeps_two_teams(mocker):
    mock_buttons = mocker.patch("elara.team_router.send_interactive_buttons", return_value=True)

    send_team_selection_prompt(KANAV_PHONE)

    mock_buttons.assert_called_once()
    buttons = mock_buttons.call_args[0][2]
    button_ids = [b["id"] for b in buttons]

    assert "team_sel_facilities" in button_ids
    assert "team_sel_elara" in button_ids
    assert "team_sel_factech" not in button_ids
    assert len(buttons) == 2


def test_developer_switch_to_factech_button(mocker):
    mocker.patch("clients.flows.handle_client_hi")
    mock_send_text = mocker.patch("elara.team_router.send_text")

    handled = route_incoming_message(DEVELOPER_PHONE, button_id="team_sel_factech")

    assert handled is True
    assert get_active_team(DEVELOPER_PHONE) == "factech"
    mock_send_text.assert_called()
    sent_text = mock_send_text.call_args[0][1]
    assert "Factech Automation" in sent_text


def test_developer_switch_to_factech_text_command(mocker):
    mocker.patch("clients.flows.handle_client_hi")
    mock_send_text = mocker.patch("elara.team_router.send_text")

    handled = route_incoming_message(DEVELOPER_PHONE, text="switch to factech")

    assert handled is True
    assert get_active_team(DEVELOPER_PHONE) == "factech"


def test_developer_switch_to_factech_numeric_3(mocker):
    mocker.patch("clients.flows.handle_client_hi")
    mocker.patch("elara.team_router.send_text")

    set_active_team(DEVELOPER_PHONE, "facilities")
    handled = route_incoming_message(DEVELOPER_PHONE, text="3")

    assert handled is True
    assert get_active_team(DEVELOPER_PHONE) == "factech"


def test_developer_client_lookup_only_in_factech_mode():
    set_active_team(DEVELOPER_PHONE, "facilities")
    assert lookup_clients_by_phone(DEVELOPER_PHONE) == []
    assert get_active_client_context(DEVELOPER_PHONE) is None

    set_active_team(DEVELOPER_PHONE, "factech")
    clients = lookup_clients_by_phone(DEVELOPER_PHONE)
    assert len(clients) == 1
    assert clients[0]["company_name"] == "Good Earth Infra (Dev Test)"
    assert clients[0]["unit_number"] == "001"

    ctx = get_active_client_context(DEVELOPER_PHONE)
    assert ctx is not None
    assert ctx["company_name"] == "Good Earth Infra (Dev Test)"


def test_developer_factech_mode_switch_back_to_facilities(mocker):
    set_active_team(DEVELOPER_PHONE, "factech")
    mocker.patch("facilities.flows.home.show_home")
    mocker.patch("elara.team_router.send_text")

    handled = route_incoming_message(DEVELOPER_PHONE, text="switch to facilities")

    assert handled is True
    assert get_active_team(DEVELOPER_PHONE) == "facilities"


def test_developer_factech_mode_switch_back_to_elara(mocker):
    set_active_team(DEVELOPER_PHONE, "factech")
    mocker.patch("elara.flows.home.show_elara_home")
    mocker.patch("elara.team_router.send_text")

    handled = route_incoming_message(DEVELOPER_PHONE, text="switch to elara")

    assert handled is True
    assert get_active_team(DEVELOPER_PHONE) == "elara"


def test_developer_factech_mode_bypasses_for_client_messages(mocker):
    set_active_team(DEVELOPER_PHONE, "factech")

    # When developer sends "hello", "1", or complaint text while in Factech mode,
    # team_router must return False so it flows into Factech client handler.
    handled = route_incoming_message(DEVELOPER_PHONE, text="hello")
    assert handled is False

    handled_complaint = route_incoming_message(DEVELOPER_PHONE, text="AC not cooling in unit 001")
    assert handled_complaint is False
