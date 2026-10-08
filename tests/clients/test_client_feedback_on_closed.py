from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch

from clients.flows import (
    send_post_complaint_options,
    handle_client_button_reply,
    handle_client_text,
    has_active_client_flow,
    handle_feedback_closed_complaints_initiation,
)
from feedback.sheets import get_closed_complaints_for_client


@pytest.fixture(autouse=True)
def clean_db(mocker):
    # Mock Supabase
    mock_db = MagicMock()
    mock_db.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mock_db.upsert.return_value.execute.return_value = MagicMock(data=[])
    mock_db.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)
    mocker.patch("feedback.session_store._sessions", {})
    mocker.patch("feedback.sheets.save_session_to_sheet", return_value=True)
    mocker.patch("feedback.sheets.remove_session_from_sheet", return_value=True)
    yield


# ── 1. "What would you like to do next?" Menu Options ──────────────────────────

def test_post_complaint_options_includes_feedback(mocker):
    """Verifies that send_post_complaint_options contains Feedback on Closed option."""
    mock_btn = mocker.patch("clients.flows.send_interactive_buttons", return_value=True)
    client = {"company_name": "Test Co", "unit_number": "101", "mobile_number": "919999999999"}

    send_post_complaint_options("919999999999", client)

    mock_btn.assert_called_once()
    buttons = mock_btn.call_args[0][2]
    btn_ids = [b["id"] for b in buttons]
    assert "feedback_closed_complaints" in btn_ids
    assert any("Feedback" in b["title"] for b in buttons)


def test_check_complaint_status_menu_includes_feedback(mocker):
    """Verifies that active complaint status check menu includes Feedback on Closed option."""
    mocker.patch("clients.flows.send_text")
    mocker.patch("clients.flows.get_complaints", return_value=[
        {
            "complaintId": "B2-00455",
            "nature": "Electrical",
            "description": "Testing Render logs",
            "status": "In Progress",
            "updated_at": "2026-10-06 15:39:37",
        }
    ])
    mock_btn = mocker.patch("clients.flows.send_interactive_buttons", return_value=True)
    mocker.patch("clients.flows.lookup_clients_by_phone", return_value=[
        {"company_name": "Test Co", "unit_number": "101", "mobile_number": "919999999999"}
    ])

    handle_client_button_reply("919999999999", "check_complaint_status")

    mock_btn.assert_called_once()
    body = mock_btn.call_args[0][1]
    assert "What would you like to do next?" in body
    buttons = mock_btn.call_args[0][2]
    btn_ids = [b["id"] for b in buttons]
    assert "feedback_closed_complaints" in btn_ids


# ── 2. Google Sheet Closed Complaints Lookup ──────────────────────────────────

def test_get_closed_complaints_for_client_matching(mocker):
    """Verifies get_closed_complaints_for_client filters for closed status and client phone."""
    mock_records = [
        # Closed complaint for client
        {
            "Complaint ID": "B2-00123",
            "Status": "Closed",
            "Client Phone": "919999999999",
            "Client Name / User": "Acme Corp",
            "Unit No": "101",
            "Complaint Nature": "HVAC",
            "Complaint Details": "AC not cooling",
            "Closed At": "2026-10-01 10:00:00",
            "Building": "GEBB2",
            "Feedback Status": "",
        },
        # Open complaint for client — should be excluded
        {
            "Complaint ID": "B2-00124",
            "Status": "In Progress",
            "Client Phone": "919999999999",
            "Client Name / User": "Acme Corp",
            "Unit No": "101",
            "Complaint Nature": "Electrical",
            "Complaint Details": "Light issue",
            "Closed At": "",
            "Building": "GEBB2",
            "Feedback Status": "",
        },
        # Closed complaint for another tenant — should be excluded
        {
            "Complaint ID": "B1-00999",
            "Status": "Closed",
            "Client Phone": "918888888888",
            "Client Name / User": "Other Corp",
            "Unit No": "505",
            "Complaint Nature": "Plumbing",
            "Complaint Details": "Leakage",
            "Closed At": "2026-10-02 12:00:00",
            "Building": "GEBB1",
            "Feedback Status": "",
        },
    ]

    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = mock_records
    mocker.patch("feedback.sheets._get_worksheet", return_value=mock_ws)
    mocker.patch("feedback.sheets._master_records_cache", None)

    results = get_closed_complaints_for_client("919999999999", unit_no="101", company_name="Acme Corp")

    assert len(results) == 1
    assert results[0]["complaintId"] == "B2-00123"
    assert results[0]["complaintNature"] == "HVAC"
    assert results[0]["building"] == "GEBB2"


# ── 3. Number-wise Display of Closed Complaints ───────────────────────────────

def test_display_closed_complaints_number_wise(mocker):
    """Verifies that multiple closed complaints are shown number-wise with the exact prompt."""
    closed_items = [
        {"complaintId": "B2-00123", "complaintNature": "HVAC", "clientPhone": "919999999999"},
        {"complaintId": "B2-00145", "complaintNature": "Electrical", "clientPhone": "919999999999"},
        {"complaintId": "B2-00167", "complaintNature": "Plumbing", "clientPhone": "919999999999"},
    ]
    mocker.patch("feedback.sheets.get_closed_complaints_for_client", return_value=closed_items)
    mock_send_text = mocker.patch("clients.flows.send_text")
    mocker.patch("clients.flows.send_interactive_buttons", return_value=False)

    mock_db = MagicMock()
    mock_upsert = MagicMock()
    mock_db.upsert.return_value = mock_upsert
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)

    client = {"company_name": "Acme Corp", "unit_number": "101", "mobile_number": "919999999999"}
    handle_feedback_closed_complaints_initiation("919999999999", client)

    # State must be set to AWAITING_CLIENT_FEEDBACK_COMPLAINT_SELECT
    mock_db.upsert.assert_called_once()
    upsert_data = mock_db.upsert.call_args[0][0]
    assert upsert_data["action"] == "AWAITING_CLIENT_FEEDBACK_COMPLAINT_SELECT"
    assert len(upsert_data["metadata"]["closed_complaints"]) == 3

    # Text must show number-wise list and exact question
    sent_msg = mock_send_text.call_args[0][1]
    assert "1. Complaint #B2-00123" in sent_msg
    assert "2. Complaint #B2-00145" in sent_msg
    assert "3. Complaint #B2-00167" in sent_msg
    assert "Please enter the number of the complaint for which you would like to give feedback." in sent_msg


# ── 4. No Closed Complaints Handling ──────────────────────────────────────────

def test_no_closed_complaints_shows_clear_message(mocker):
    """Verifies that user with no closed complaints receives a clear message and menu."""
    mocker.patch("feedback.sheets.get_closed_complaints_for_client", return_value=[])
    mocker.patch("clients.flows.get_complaints", return_value=[])
    mock_send_text = mocker.patch("clients.flows.send_text")
    mock_btn = mocker.patch("clients.flows.send_interactive_buttons", return_value=True)

    client = {"company_name": "Acme Corp", "unit_number": "101", "mobile_number": "919999999999"}
    handle_feedback_closed_complaints_initiation("919999999999", client)

    mock_btn.assert_called_once()
    msg = mock_btn.call_args[0][1]
    assert "no closed complaints" in msg.lower()
    buttons = mock_btn.call_args[0][2]
    btn_ids = [b["id"] for b in buttons]
    assert "log_new_complaint" in btn_ids
    assert "client_main_menu" in btn_ids


# ── 5. Selecting Complaint by Number Triggers Feedback Flow ──────────────────

def test_client_selects_complaint_by_number(mocker):
    """Verifies that entering '1' triggers the existing feedback flow for that complaint."""
    closed_items = [
        {
            "complaintId": "B2-00123",
            "complaintNature": "HVAC",
            "clientName": "Acme Corp",
            "unitNo": "101",
            "complaintDetails": "AC repair",
            "building": "GEBB2",
            "closedAt": "2026-10-01 10:00:00",
            "rowIndex": 5,
        },
        {
            "complaintId": "B2-00145",
            "complaintNature": "Electrical",
            "clientName": "Acme Corp",
            "unitNo": "101",
            "building": "GEBB2",
        },
    ]

    mock_state_res = MagicMock()
    mock_state_res.data = [{
        "action": "AWAITING_CLIENT_FEEDBACK_COMPLAINT_SELECT",
        "metadata": {
            "client_context": {"company_name": "Acme Corp", "unit_number": "101"},
            "closed_complaints": closed_items,
        },
    }]

    mock_db = MagicMock()
    mock_db.select.return_value.eq.return_value.execute.return_value = mock_state_res
    mock_delete = MagicMock()
    mock_db.delete.return_value.eq.return_value.execute.return_value = mock_delete
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)

    mock_initiate = mocker.patch("feedback.engine.initiate_feedback", return_value={"status": "ok"})
    mock_send_text = mocker.patch("clients.flows.send_text")

    handled = handle_client_text("919999999999", "1")

    assert handled is True
    # State cleared
    mock_db.delete.assert_called_once()

    # Reuses existing initiate_feedback
    mock_initiate.assert_called_once()
    payload = mock_initiate.call_args[0][0]
    assert payload["complaintId"] == "B2-00123"
    assert payload["clientPhone"] == "919999999999"
    assert payload["building"] == "GEBB2"
    assert payload["complaintNature"] == "HVAC"


def test_client_selects_complaint_by_complaint_id(mocker):
    """Verifies that entering '#B2-00145' also identifies the complaint properly."""
    closed_items = [
        {"complaintId": "B2-00123", "complaintNature": "HVAC", "building": "GEBB2"},
        {"complaintId": "B2-00145", "complaintNature": "Electrical", "building": "GEBB2"},
    ]

    mock_state_res = MagicMock()
    mock_state_res.data = [{
        "action": "AWAITING_CLIENT_FEEDBACK_COMPLAINT_SELECT",
        "metadata": {
            "client_context": {"company_name": "Acme Corp", "unit_number": "101"},
            "closed_complaints": closed_items,
        },
    }]

    mock_db = MagicMock()
    mock_db.select.return_value.eq.return_value.execute.return_value = mock_state_res
    mock_db.delete.return_value.eq.return_value.execute.return_value = MagicMock()
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)

    mock_initiate = mocker.patch("feedback.engine.initiate_feedback", return_value={"status": "ok"})
    mocker.patch("clients.flows.send_text")

    handled = handle_client_text("919999999999", "#B2-00145")

    assert handled is True
    mock_initiate.assert_called_once()
    assert mock_initiate.call_args[0][0]["complaintId"] == "B2-00145"


# ── 6. Invalid Number Validation ──────────────────────────────────────────────

def test_invalid_number_asks_for_valid_complaint_number(mocker):
    """Verifies that entering an invalid number asks user to select a valid number and preserves state."""
    closed_items = [
        {"complaintId": "B2-00123", "complaintNature": "HVAC"},
        {"complaintId": "B2-00145", "complaintNature": "Electrical"},
    ]

    mock_state_res = MagicMock()
    mock_state_res.data = [{
        "action": "AWAITING_CLIENT_FEEDBACK_COMPLAINT_SELECT",
        "metadata": {
            "client_context": {"company_name": "Acme Corp"},
            "closed_complaints": closed_items,
        },
    }]

    mock_db = MagicMock()
    mock_db.select.return_value.eq.return_value.execute.return_value = mock_state_res
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)

    mock_initiate = mocker.patch("feedback.engine.initiate_feedback")
    mock_send_text = mocker.patch("clients.flows.send_text")

    # Enter out-of-range number "5"
    handled = handle_client_text("919999999999", "5")

    assert handled is True
    # initiate_feedback must NOT be called
    mock_initiate.assert_not_called()

    # User informed to select valid number
    mock_send_text.assert_called_once()
    msg = mock_send_text.call_args[0][1]
    assert "valid complaint number" in msg.lower()
    assert "1 to 2" in msg


def test_entering_another_users_complaint_id_rejected(mocker):
    """Verifies that entering a complaint ID that does not belong to the user is rejected."""
    closed_items = [
        {"complaintId": "B2-00123", "complaintNature": "HVAC"},
    ]

    mock_state_res = MagicMock()
    mock_state_res.data = [{
        "action": "AWAITING_CLIENT_FEEDBACK_COMPLAINT_SELECT",
        "metadata": {
            "client_context": {"company_name": "Acme Corp"},
            "closed_complaints": closed_items,
        },
    }]

    mock_db = MagicMock()
    mock_db.select.return_value.eq.return_value.execute.return_value = mock_state_res
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)

    mock_initiate = mocker.patch("feedback.engine.initiate_feedback")
    mock_send_text = mocker.patch("clients.flows.send_text")

    # Try to submit feedback for another user's complaint
    handled = handle_client_text("919999999999", "B1-99999")

    assert handled is True
    mock_initiate.assert_not_called()
    assert "valid complaint number" in mock_send_text.call_args[0][1].lower()


# ── 7. Conversation State Preservation ────────────────────────────────────────

def test_has_active_client_flow_includes_feedback_select(mocker):
    """Verifies that has_active_client_flow recognizes AWAITING_CLIENT_FEEDBACK_COMPLAINT_SELECT."""
    mock_db = MagicMock()
    mock_db.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[
        {"action": "AWAITING_CLIENT_FEEDBACK_COMPLAINT_SELECT"}
    ])
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)

    assert has_active_client_flow("919999999999") is True


def test_cancel_feedback_selection_returns_to_menu(mocker):
    """Verifies that typing 'cancel' clears state and returns user to post-complaint menu."""
    mock_state_res = MagicMock()
    mock_state_res.data = [{
        "action": "AWAITING_CLIENT_FEEDBACK_COMPLAINT_SELECT",
        "metadata": {"client_context": {"company_name": "Acme Corp"}},
    }]

    mock_db = MagicMock()
    mock_db.select.return_value.eq.return_value.execute.return_value = mock_state_res
    mock_db.delete.return_value.eq.return_value.execute.return_value = MagicMock()
    mocker.patch("clients.flows.supabase.table", return_value=mock_db)

    mock_send_text = mocker.patch("clients.flows.send_text")
    mock_post_opts = mocker.patch("clients.flows.send_post_complaint_options")

    handled = handle_client_text("919999999999", "cancel")

    assert handled is True
    mock_db.delete.assert_called_once()
    mock_post_opts.assert_called_once()


# ── 8. Main Menu List Message & Routing ───────────────────────────────────────

def test_welcome_menu_sends_list_message_with_feedback(mocker):
    """Verifies that send_client_welcome_menu sends an interactive list message with all 4 options including feedback."""
    from clients.flows import send_client_welcome_menu

    mock_list = mocker.patch("clients.flows.send_list_message", return_value=True)
    client = {
        "admin_name": "Abhijeet",
        "company_name": "Good Earth Infra (Dev Test)",
        "building": "Business Bay-II",
        "unit_number": "GEEBTWOTest",
    }

    send_client_welcome_menu("917717754421", client)

    mock_list.assert_called_once()
    args = mock_list.call_args[0]
    to_num, body, btn_text, sections = args
    assert to_num == "917717754421"
    assert "Good Earth Infra (Dev Test)" in body
    assert btn_text == "Open Menu"

    # Verify rows inside section
    assert len(sections) == 1
    rows = sections[0]["rows"]
    row_ids = [r["id"] for r in rows]
    assert row_ids == [
        "log_new_complaint",
        "check_complaint_status",
        "complaint_history",
        "feedback_closed_complaints",
    ]
    fb_row = next(r for r in rows if r["id"] == "feedback_closed_complaints")
    assert "Feedback" in fb_row["title"]
    assert "closed complaints" in fb_row["description"].lower()


def test_welcome_menu_fallback_includes_feedback(mocker):
    """Verifies that send_client_welcome_menu text fallback includes option 4 for feedback."""
    from clients.flows import send_client_welcome_menu

    mocker.patch("clients.flows.send_list_message", return_value=False)
    mock_text = mocker.patch("clients.flows.send_text", return_value=True)

    client = {
        "admin_name": "Abhijeet",
        "company_name": "Good Earth Infra",
        "building": "Business Bay-II",
        "unit_number": "GEEBTWOTest",
    }

    send_client_welcome_menu("917717754421", client)

    mock_text.assert_called_once()
    text = mock_text.call_args[0][1]
    assert "1️⃣ *Log New Complaint*" in text
    assert "2️⃣ *Check Status*" in text
    assert "3️⃣ *Complaint History*" in text
    assert "4️⃣ *Give Feedback on Closed Complaints*" in text

