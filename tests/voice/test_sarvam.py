import pytest
import os
from whatsapp.audio_handler import handle_voice_note, transcribe_with_sarvam, transcribe_with_groq

def test_transcribe_with_sarvam(mocker):
    mocker.patch("config.SARVAM_API_KEY", "test_key")
    
    mock_post = mocker.patch("requests.post")
    mock_post.return_value.json.return_value = {"transcript": "Update the waterproofing task."}
    
    # We mock open since we don't have a real audio file
    mocker.patch("builtins.open", mocker.mock_open(read_data=b"dummy audio"))
    
    transcript = transcribe_with_sarvam("dummy.ogg")
    
    assert transcript == "Update the waterproofing task."
    mock_post.assert_called_once()
    
def test_transcribe_with_groq(mocker):
    mocker.patch("config.GROQCLOUD_API_KEY", "test_key")
    
    # Mock Groq client
    mock_groq_client = mocker.MagicMock()
    mock_groq_client.audio.transcriptions.create.return_value = "Update the waterproofing task."
    mocker.patch("groq.Groq", return_value=mock_groq_client)
    
    mocker.patch("builtins.open", mocker.mock_open(read_data=b"dummy audio"))
    
    transcript = transcribe_with_groq("dummy.ogg")
    
    assert transcript == "Update the waterproofing task."

def test_handle_voice_note_success(mocker):
    # Mock download to return dummy path
    mocker.patch("whatsapp.audio_handler.download_audio", return_value="/tmp/gei_audio_test.ogg")
    
    # Mock transcription
    mocker.patch("whatsapp.audio_handler.transcribe_audio", return_value="Complete the task")
    
    # Mock cleanup so it doesn't try to delete
    mock_cleanup = mocker.patch("whatsapp.audio_handler.cleanup_audio")
    
    result = handle_voice_note("media_123", "1234567890")
    
    assert result["success"] is True
    assert result["transcript"] == "Complete the task"
    assert result["error"] is None
    
    mock_cleanup.assert_called_once_with("/tmp/gei_audio_test.ogg")

def test_handle_voice_note_empty_transcript(mocker, caplog):
    caplog.set_level("CRITICAL")
    mocker.patch("whatsapp.audio_handler.download_audio", return_value="/tmp/gei_audio_test.ogg")
    mocker.patch("whatsapp.audio_handler.transcribe_audio", return_value="")
    mocker.patch("whatsapp.audio_handler.cleanup_audio")
    
    result = handle_voice_note("media_123", "1234567890")
    
    assert result["success"] is False
    assert result["error_type"] == "empty_transcript"

def test_handle_voice_note_download_failed(mocker, caplog):
    caplog.set_level("CRITICAL")
    mocker.patch("whatsapp.audio_handler.download_audio", side_effect=Exception("Network error"))
    
    result = handle_voice_note("media_123", "1234567890")
    
    assert result["success"] is False
    assert result["error_type"] == "download_failed"
