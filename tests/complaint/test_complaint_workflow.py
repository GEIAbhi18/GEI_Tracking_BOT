# pyrefly: ignore [missing-import]
import pytest
from feedback.engine import initiate_feedback, handle_flow_response, handle_feedback_reply
from feedback.session_store import _sessions

@pytest.fixture(autouse=True)
def clean_sessions(mocker):
    mocker.patch("feedback.sheets.save_session_to_sheet", return_value=True)
    mocker.patch("feedback.sheets.remove_session_from_sheet", return_value=True)
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


def test_send_flow_template_spacing_and_clean_template(mocker):
    from feedback.flow_sender import send_flow_template
    mock_post_wa = mocker.patch("feedback.flow_sender._post_wa", return_value=True)
    mock_send_text = mocker.patch("whatsapp.ux.send_text", return_value=True)

    success = send_flow_template(
        phone="917717754421",
        client_name="Chaitanya Test",
        complaint_id="B2-00090",
        complaint_nature="Civil",
        unit_no="GEEBTWOTest",
        complaint_details="Others : test",
    )
    assert success is True

    # Verify formatted text message sent with line breaks between each part
    mock_send_text.assert_called_once()
    sent_text = mock_send_text.call_args[0][1]
    assert "Hello Chaitanya Test," in sent_text
    assert "A complaint has been resolved in FacTech." in sent_text
    assert "ID: B2-00090" in sent_text
    assert "Unit: GEEBTWOTest" in sent_text
    assert "Nature: Civil" in sent_text
    assert "Sub Nature: Others : test" in sent_text
    assert "Closed: " in sent_text
    assert "\n\n" in sent_text

    # Verify template payload has clean display_name without newlines
    mock_post_wa.assert_called_once()
    payload = mock_post_wa.call_args[0][0]
    param_text = payload["template"]["components"][0]["parameters"][0]["text"]
    assert param_text == "Chaitanya Test"
    assert "\n" not in param_text
