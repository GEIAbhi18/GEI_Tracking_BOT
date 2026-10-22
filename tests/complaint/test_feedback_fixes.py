import os
import pytest
from unittest.mock import MagicMock, patch
from feedback.engine import handle_flow_response, _complete_feedback
from feedback.session_store import set_session, remove_session
from feedback.sheets import (
    append_feedback_duplicate,
    check_feedback_already_received,
    _cached_get_all_values,
    invalidate_cache,
)


@pytest.fixture(autouse=True)
def cleanup_session(mocker):
    mocker.patch("feedback.session_store._backup_session_async")
    mocker.patch("feedback.session_store._remove_from_sheet_sync")
    phone = "919876543210"
    remove_session(phone)
    yield
    remove_session(phone)


# ── Fix 2b: Flow Token Validation Tests ────────────────────────────────────────

def test_flow_token_mismatch_rejected(mocker):
    """Verifies that if flow_token does not match active session complaint ID, it is rejected."""
    phone = "919876543210"
    session_data = {
        "complaintId": "B2-00455",
        "clientName": "Test Client",
        "stage": "WAITING_FLOW",
        "building": "GEBB2",
        "unitNo": "201",
    }
    set_session(phone, session_data)

    mock_send = mocker.patch("feedback.engine._send_wa")

    response_data = {
        "flow_token": "B2-00999",  # Different complaint ID!
        "resolution_rating": "5",
        "facility_team_rating": "5",
        "overall_rating": "5",
        "comments": "Great",
    }

    result = handle_flow_response(phone, response_data)
    assert result is False
    mock_send.assert_called_once()
    assert "different complaint" in mock_send.call_args[0][1]


def test_flow_token_valid_accepted(mocker):
    """Verifies that matching flow_token is accepted and processed."""
    phone = "919876543210"
    session_data = {
        "complaintId": "B2-00455",
        "clientName": "Test Client",
        "stage": "WAITING_FLOW",
        "building": "GEBB2",
        "unitNo": "201",
    }
    set_session(phone, session_data)

    mocker.patch("feedback.engine._send_wa")
    mock_complete = mocker.patch("feedback.engine._complete_feedback")

    response_data = {
        "flow_token": "B2-00455",  # Matching complaint ID
        "resolution_rating": "5",
        "facility_team_rating": "5",
        "overall_rating": "5",
        "comments": "Great service",
    }

    result = handle_flow_response(phone, response_data)
    assert result is True
    mock_complete.assert_called_once()


# ── Fix 2c: Score Validation Tests ─────────────────────────────────────────────

def test_zero_scores_rejected(mocker):
    """Verifies that scores defaulting to 0 are rejected instead of triggering false escalations."""
    phone = "919876543210"
    session_data = {
        "complaintId": "B2-00455",
        "clientName": "Test Client",
        "stage": "WAITING_FLOW",
    }
    set_session(phone, session_data)

    mock_send = mocker.patch("feedback.engine._send_wa")

    # Flow response with 0 or missing scores
    response_data = {
        "flow_token": "B2-00455",
        "resolution_rating": "0",
        "facility_team_rating": 0,
        "overall_rating": "0",
        "comments": "ok",
    }

    result = handle_flow_response(phone, response_data)
    assert result is False
    mock_send.assert_called_once()
    assert "missing or invalid" in mock_send.call_args[0][1]


def test_missing_score_fields_rejected(mocker):
    """Verifies that missing rating fields in flow response are rejected."""
    phone = "919876543210"
    session_data = {
        "complaintId": "B2-00455",
        "clientName": "Test Client",
        "stage": "WAITING_FLOW",
    }
    set_session(phone, session_data)

    mock_send = mocker.patch("feedback.engine._send_wa")

    response_data = {
        "flow_token": "B2-00455",
        "resolution_rating": "5",
        # facility_team_rating and overall_rating are missing
        "comments": "good",
    }

    result = handle_flow_response(phone, response_data)
    assert result is False
    mock_send.assert_called_once()
    assert "missing or invalid" in mock_send.call_args[0][1]


def test_invalid_score_string_rejected(mocker):
    """Verifies that non-integer score strings are gracefully rejected."""
    phone = "919876543210"
    session_data = {
        "complaintId": "B2-00455",
        "clientName": "Test Client",
        "stage": "WAITING_FLOW",
    }
    set_session(phone, session_data)

    mock_send = mocker.patch("feedback.engine._send_wa")

    response_data = {
        "flow_token": "B2-00455",
        "resolution_rating": "invalid_number",
        "facility_team_rating": "5",
        "overall_rating": "5",
    }

    result = handle_flow_response(phone, response_data)
    assert result is False
    mock_send.assert_called_once()
    assert "invalid rating values" in mock_send.call_args[0][1]


# ── Fix 1: Duplicate Feedback Redirection Tests ────────────────────────────────

def test_duplicate_feedback_redirected_to_duplicates_sheet(mocker):
    """Verifies that if feedback was already received, it is appended to Feedback_Duplicates sheet."""
    phone = "919876543210"
    session_data = {
        "complaintId": "B2-00455",
        "clientName": "Acme Corp",
        "building": "GEBB2",
        "unitNo": "201",
        "complaintNature": "Electrical",
    }

    mocker.patch("feedback.engine._send_wa")
    # Simulate that this complaint ALREADY had feedback received
    mocker.patch("feedback.sheets.check_feedback_already_received", return_value=True)

    mock_append_dup = mocker.patch("feedback.sheets.append_feedback_duplicate", return_value=True)
    mock_update_master = mocker.patch("feedback.sheets.update_master_feedback")
    mock_update_bldg = mocker.patch("feedback.sheets.update_building_sheet_feedback")
    mock_append_escalation = mocker.patch("feedback.sheets.append_escalation")

    _complete_feedback(phone, session_data, 5, 5, 5, "Already reviewed")

    # Must append to Feedback_Duplicates
    mock_append_dup.assert_called_once()
    call_args = mock_append_dup.call_args
    assert call_args[0][0] == "B2-00455"
    assert call_args[0][1]["Remarks"] == "Already reviewed"
    assert call_args[0][1]["Resolution Score"] == 5

    # Must NOT touch MASTER, building sheet, or escalations
    mock_update_master.assert_not_called()
    mock_update_bldg.assert_not_called()
    mock_append_escalation.assert_not_called()


def test_first_time_feedback_updates_master_and_building_sheets(mocker):
    """Verifies that non-duplicate feedback updates the MASTER and building sheets (Fix 2d)."""
    phone = "919876543210"
    session_data = {
        "complaintId": "B2-00455",
        "clientName": "Acme Corp",
        "building": "GEBB2",
        "unitNo": "201",
        "complaintNature": "Electrical",
    }

    mocker.patch("feedback.engine._send_wa")
    # Simulate first-time submission (not duplicate)
    mocker.patch("feedback.sheets.check_feedback_already_received", return_value=False)

    mock_append_dup = mocker.patch("feedback.sheets.append_feedback_duplicate")
    mock_update_master = mocker.patch("feedback.sheets.update_master_feedback", return_value=True)
    mock_update_bldg = mocker.patch("feedback.sheets.update_building_sheet_feedback", return_value=True)

    _complete_feedback(phone, session_data, 5, 5, 5, "All good")

    # Must NOT call duplicates sheet
    mock_append_dup.assert_not_called()

    # Must update MASTER sheet (Fix 2d) and building sheet
    mock_update_master.assert_called_once()
    assert mock_update_master.call_args[0][0] == "B2-00455"
    mock_update_bldg.assert_called_once()


# ── Fix 2a: Quota Protection Caching Tests ─────────────────────────────────────

def test_cached_get_all_values_prevents_redundant_sheets_calls(mocker):
    """Verifies Fix 2a: _cached_get_all_values caches sheet data to prevent 429 quota errors."""
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [["Header 1", "Header 2"], ["Val 1", "Val 2"]]
    mocker.patch("feedback.sheets._get_worksheet", return_value=mock_ws)

    invalidate_cache("TestSheet")

    # First call: hits ws.get_all_values()
    res1 = _cached_get_all_values("TestSheet")
    assert len(res1) == 2
    assert mock_ws.get_all_values.call_count == 1

    # Second call within TTL: uses cache, does NOT hit Google Sheets API again
    res2 = _cached_get_all_values("TestSheet")
    assert res2 == res1
    assert mock_ws.get_all_values.call_count == 1  # Unchanged!


# ── Part B: Closed Complaints Filter Tests ─────────────────────────────────────

def test_feedback_menu_filters_already_rated_complaints(mocker):
    """Verifies Part B: Complaints with Feedback Status == 'Received' are omitted from feedback menu."""
    from clients.flows import handle_feedback_closed_complaints_initiation

    # MASTER sheet returned complaints, one already has feedback 'Received'
    mock_records = [
        {
            "complaintId": "B2-00101",
            "complaintNature": "HVAC",
            "feedbackStatus": "Received",  # Already rated -> must be filtered
        },
        {
            "complaintId": "B2-00102",
            "complaintNature": "Electrical",
            "feedbackStatus": "",  # Not rated -> should be included
        },
    ]

    mocker.patch("feedback.sheets.get_closed_complaints_for_client", return_value=mock_records)
    mock_send = mocker.patch("clients.flows.send_text")
    mocker.patch("clients.flows.send_interactive_buttons", return_value=False)
    mocker.patch("clients.flows.supabase.table")

    client = {"company_name": "Acme Corp", "unit_number": "101", "mobile_number": "919999999999"}
    handle_feedback_closed_complaints_initiation("919999999999", client)

    # Only B2-00102 should be in the message, B2-00101 should be filtered out
    sent_msg = mock_send.call_args[0][1]
    assert "B2-00102" in sent_msg
    assert "B2-00101" not in sent_msg
