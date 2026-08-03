import pytest
from unittest.mock import MagicMock, AsyncMock
from core.intent_handlers import perform_update
from core.update_engine import continue_conversation

@pytest.mark.asyncio
async def test_perform_update_explicit_progress_and_note(mocker):
    mock_send_reply = AsyncMock()
    mock_save_update = mocker.patch("core.intent_handlers.save_update")
    mock_set_state = mocker.patch("core.intent_handlers.set_state")
    mocker.patch("core.intent_handlers.get_context", return_value={})
    mocker.patch("core.intent_handlers.get_all_tasks", return_value=[{"id": "t-101", "name": "Set meeting with Goyal", "progress": 0}])
    mocker.patch("core.intent_handlers.resolve_task_from_list", return_value={"id": "t-101", "name": "Set meeting with Goyal", "progress": 0})
    mocker.patch("core.intent_handlers._resolve_user", return_value={"id": "user-123"})
    mocker.patch("core.intent_handlers.update_context")

    await perform_update("Set meeting with Goyal", "25%", "user-123", mock_send_reply, note="meeting requested")

    # Assert progress is 25
    mock_save_update.assert_called_once_with("t-101", 25, "None", [], "user-123", new_deadline=None, note="meeting requested")
    # Assert state is set for follow-up note prompt
    mock_set_state.assert_called_once()
    assert mock_set_state.call_args[0][1]["action"] == "task_update_note"
    # Assert reply asks for additional notes
    reply_text = mock_send_reply.call_args[0][0]
    assert "Update saved ✅" in reply_text
    assert "Progress: 25%" in reply_text
    assert "Would you like to add any additional notes" in reply_text


@pytest.mark.asyncio
async def test_perform_update_default_progress_10_to_35(mocker):
    mock_send_reply = AsyncMock()
    mock_save_update = mocker.patch("core.intent_handlers.save_update")
    mock_set_state = mocker.patch("core.intent_handlers.set_state")
    mocker.patch("core.intent_handlers.get_context", return_value={})
    mocker.patch("core.intent_handlers.get_all_tasks", return_value=[{"id": "t-102", "name": "Inspect site generator", "progress": 0}])
    mocker.patch("core.intent_handlers.resolve_task_from_list", return_value={"id": "t-102", "name": "Inspect site generator", "progress": 0})
    mocker.patch("core.intent_handlers._resolve_user", return_value={"id": "user-123"})
    mocker.patch("core.intent_handlers.update_context")

    # Pass progress_str = None
    await perform_update("Inspect site generator", None, "user-123", mock_send_reply, note="initial check done")

    mock_save_update.assert_called_once()
    saved_progress = mock_save_update.call_args[0][1]
    # Assert default progress is in range 10 to 35
    assert 10 <= saved_progress <= 35


@pytest.mark.asyncio
async def test_continue_conversation_task_update_note_no(mocker):
    mock_send_reply = AsyncMock()
    mock_clear_state = mocker.patch("core.update_engine.clear_state")

    state = {
        "action": "task_update_note",
        "step": "waiting_for_note",
        "task_id": "t-101",
        "task_name": "Set meeting with Goyal",
        "initial_note": "meeting requested"
    }

    await continue_conversation("No", "user-123", state, [], mock_send_reply)

    mock_clear_state.assert_called_once_with("user-123")
    reply_text = mock_send_reply.call_args[0][0]
    assert "Task update completed for 'Set meeting with Goyal'" in reply_text


@pytest.mark.asyncio
async def test_continue_conversation_task_update_note_with_comment(mocker):
    mock_send_reply = AsyncMock()
    mock_clear_state = mocker.patch("core.update_engine.clear_state")
    mocker.patch("core.update_engine._resolve_user_ue", return_value={"id": "user-123"})
    mocker.patch("tasks.timeline.add_timeline_event")
    mock_supabase = mocker.patch("db.supabase")

    state = {
        "action": "task_update_note",
        "step": "waiting_for_note",
        "task_id": "t-101",
        "task_name": "Set meeting with Goyal",
        "initial_note": "meeting requested"
    }

    await continue_conversation("Meeting scheduled for Friday at 3 PM", "user-123", state, [], mock_send_reply)

    mock_clear_state.assert_called_once_with("user-123")
    mock_supabase.table.return_value.update.assert_called_once_with({"notes": "meeting requested\nMeeting scheduled for Friday at 3 PM"})
    reply_text = mock_send_reply.call_args[0][0]
    assert "Note added to task 'Set meeting with Goyal' successfully!" in reply_text
