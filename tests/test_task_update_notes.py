import pytest
from unittest.mock import MagicMock, AsyncMock
from core.intent_handlers import perform_update
from core.update_engine import continue_conversation
from whatsapp.handlers import handle_direct_task_update

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


def test_handle_direct_task_update_number_and_note(mocker):
    """Test '2 test comments and it worked' extracts task 2, generates default progress (10-35%), saves note, and displays note in update reply."""
    mocker.patch("core.context_manager.get_context", return_value={"last_task_list": ["t-1", "t-2", "t-3"]})
    mock_supabase = mocker.patch("db.supabase")

    mock_tasks = [
        {"id": "t-1", "title": "Pay water bill", "progress": 0, "status": "Pending"},
        {"id": "t-2", "title": "Dummy Test Task", "progress": 0, "status": "Pending"},
        {"id": "t-3", "title": "Notification testing", "progress": 0, "status": "Pending"},
    ]
    
    mock_query = MagicMock()
    mock_query.execute.return_value.data = mock_tasks
    mock_supabase.table.return_value.select.return_value = mock_query

    mock_save_update = mocker.patch("db.save_update")
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_set_wa_state = mocker.patch("whatsapp.handlers.set_wa_state")
    mocker.patch("tasks.timeline.add_timeline_event")

    user_info = {"id": "user-123", "name": "Abhijeet"}

    # Run direct update with "2 test comments and it worked"
    res = handle_direct_task_update("917717754421", "2 test comments and it worked", user_info)

    assert res is True
    # Verify save_update was called with task id t-2, progress in 10-35, and note='test comments and it worked'
    mock_save_update.assert_called_once()
    call_args = mock_save_update.call_args[0]
    kwargs = mock_save_update.call_args.kwargs
    assert call_args[0] == "t-2" # task_id
    assert 10 <= call_args[1] <= 35 # progress in 10-35%
    note_val = kwargs.get("note") or (call_args[5] if len(call_args) > 5 else None)
    assert note_val == "test comments and it worked" # note

    # Verify Step 1 prompt asks for notes/comments
    reply_msg = mock_send_text.call_args[0][1]
    assert "Dummy Test Task" in reply_msg
    assert "Would you like to add any notes or comments" in reply_msg

    # Verify state set to WAITING_FOR_UPDATE_NOTE
    mock_set_wa_state.assert_called_once()
    assert mock_set_wa_state.call_args[0][1] == "WAITING_FOR_UPDATE_NOTE"
