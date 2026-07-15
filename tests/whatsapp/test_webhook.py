import pytest
import json
from whatsapp.whatsapp_webhook import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_webhook_verify_success(client, mocker):
    """Test Meta webhook verification GET request."""
    # We patch the VERIFY_TOKEN in the module
    mocker.patch("whatsapp.whatsapp_webhook.VERIFY_TOKEN", "test_token")
    
    response = client.get("/webhook?hub.mode=subscribe&hub.verify_token=test_token&hub.challenge=CHALLENGE_STRING")
    
    assert response.status_code == 200
    assert response.data.decode("utf-8") == "CHALLENGE_STRING"

def test_webhook_verify_failure(client, mocker):
    """Test Meta webhook verification fails with wrong token."""
    mocker.patch("whatsapp.whatsapp_webhook.VERIFY_TOKEN", "test_token")
    
    response = client.get("/webhook?hub.mode=subscribe&hub.verify_token=wrong_token&hub.challenge=CHALLENGE_STRING")
    
    assert response.status_code == 403

def test_webhook_post_text_message(client, mocker):
    """Test incoming text message."""
    mock_thread = mocker.patch("threading.Thread")
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "1234567890",
                        "type": "text",
                        "text": {"body": "hello"}
                    }]
                }
            }]
        }]
    }
    
    response = client.post("/webhook", json=payload)
    
    assert response.status_code == 200
    assert json.loads(response.data) == {"status": "ok"}
    # Verify thread was spawned to process it
    mock_thread.assert_called()

def test_webhook_post_interactive_reply(client, mocker):
    """Test incoming interactive message (button reply)."""
    mock_thread = mocker.patch("threading.Thread")
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "1234567890",
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {"id": "test_button"}
                        }
                    }]
                }
            }]
        }]
    }
    
    response = client.post("/webhook", json=payload)
    
    assert response.status_code == 200
    assert json.loads(response.data) == {"status": "ok"}
    # Verify thread was spawned to process the interactive reply
    mock_thread.assert_called()

def test_webhook_post_audio_message(client, mocker):
    """Test incoming audio message."""
    mock_thread = mocker.patch("threading.Thread")
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "1234567890",
                        "type": "audio",
                        "audio": {"id": "audio_123"}
                    }]
                }
            }]
        }]
    }
    
    response = client.post("/webhook", json=payload)
    
    assert response.status_code == 200
    assert json.loads(response.data) == {"status": "ok"}
    mock_thread.assert_called()
