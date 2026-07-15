import pytest
from feedback.engine import initiate_feedback, handle_flow_response, handle_feedback_reply
from feedback.session_store import _sessions

@pytest.fixture(autouse=True)
def clean_sessions():
    _sessions.clear()
    yield
    _sessions.clear()

def test_initiate_feedback(mocker):
    # Mock whatsapp sending
    mock_send_flow = mocker.patch("feedback.flow_sender.send_flow_template", return_value=True)
    # Mock sheets writing
    mock_update_building = mocker.patch("feedback.sheets.update_building_sheet_feedback")
    
    complaint_data = {
        "clientPhone": "919999999999",
        "complaintId": "TT-123",
        "clientName": "Test Client",
        "building": "GETT",
        "unitNo": "101",
        "complaintNature": "Plumbing"
    }
    
    result = initiate_feedback(complaint_data)
    
    assert result["status"] == "ok"
    mock_send_flow.assert_called_once()
    mock_update_building.assert_called_once()

def test_initiate_feedback_queued(mocker):
    mocker.patch("feedback.flow_sender.send_flow_template", return_value=True)
    mocker.patch("feedback.sheets.update_building_sheet_feedback")
    
    complaint_data_1 = {
        "clientPhone": "919999999999",
        "complaintId": "C-1",
        "clientName": "Test Client",
        "building": "TT-123",
        "unitNo": "101",
        "complaintNature": "Plumbing"
    }
    
    complaint_data_2 = {
        "clientPhone": "919999999999",
        "complaintId": "C-2",
        "clientName": "Test Client",
        "building": "TT-123",
        "unitNo": "101",
        "complaintNature": "Electrical"
    }
    
    res1 = initiate_feedback(complaint_data_1)
    res2 = initiate_feedback(complaint_data_2)
    
    assert res1["status"] == "ok"
    assert res2["status"] == "queued"

def test_handle_flow_response(mocker):
    # Setup session
    mocker.patch("feedback.flow_sender.send_flow_template", return_value=True)
    mocker.patch("feedback.sheets.update_building_sheet_feedback")
    
    initiate_feedback({
        "clientPhone": "919999999999",
        "complaintId": "TT-123",
        "clientName": "Test Client",
        "building": "GETT",
        "unitNo": "101",
        "complaintNature": "Plumbing"
    })
    
    # Mock _send_wa to check thank you message
    mock_send_wa = mocker.patch("feedback.engine._send_wa")
    
    # Mock sheet writes
    mock_master = mocker.patch("feedback.sheets.update_master_feedback")
    mock_escalation = mocker.patch("feedback.sheets.append_escalation")
    
    flow_data = {
        "resolution_rating": "5",
        "facility_team_rating": "5",
        "overall_rating": "5",
        "comments": "Excellent job"
    }
    
    handled = handle_flow_response("919999999999", flow_data)
    
    assert handled is True
    mock_send_wa.assert_called_once() # Thank you message
    mock_master.assert_called_once()
    mock_escalation.assert_not_called()

def test_handle_flow_response_escalation(mocker):
    mocker.patch("feedback.flow_sender.send_flow_template", return_value=True)
    mocker.patch("feedback.sheets.update_building_sheet_feedback")
    
    initiate_feedback({
        "clientPhone": "919999999999",
        "complaintId": "TT-123",
        "clientName": "Test Client",
        "building": "GETT",
        "unitNo": "101",
        "complaintNature": "Plumbing"
    })
    
    mocker.patch("feedback.engine._send_wa")
    mocker.patch("feedback.sheets.update_master_feedback")
    mock_escalation = mocker.patch("feedback.sheets.append_escalation")
    
    flow_data = {
        "resolution_rating": "1",
        "facility_team_rating": "1",
        "overall_rating": "1",
        "comments": "Terrible job, very bad"
    }
    
    handle_flow_response("919999999999", flow_data)
    
    mock_escalation.assert_called_once()
    
def test_handle_feedback_reply_cancel(mocker):
    mocker.patch("feedback.flow_sender.send_flow_template", return_value=True)
    mocker.patch("feedback.sheets.update_building_sheet_feedback")
    
    initiate_feedback({
        "clientPhone": "919999999999",
        "complaintId": "TT-123",
        "clientName": "Test Client",
        "building": "GETT",
        "unitNo": "101",
        "complaintNature": "Plumbing"
    })
    
    mock_send_wa = mocker.patch("feedback.engine._send_wa")
    handled = handle_feedback_reply("919999999999", "CANCEL")
    
    assert handled is True
    mock_send_wa.assert_called_once()
