import pytest
from datetime import datetime
from db import (
    add_task, 
    complete_task, 
    save_update, 
    archive_task, 
    restore_task, 
    delete_task, 
    set_task_reminder,
    bulk_update_tasks
)
from tests.fixtures.factories import create_mock_task, create_mock_user

def test_add_task(mock_supabase):
    mock_execute = mock_supabase.table("tasks").insert().execute
    mock_execute.return_value.data = [{"id": "new-task-123", "title": "Test Task"}]
    
    task = add_task("project-123", "Test Task", assigned_to="user-1")
    
    assert task is not None
    assert task["id"] == "new-task-123"
    
def test_complete_task(mock_supabase):
    mock_execute = mock_supabase.table("tasks").update().eq().execute
    mock_execute.return_value.data = [{"id": "task-123", "status": "Completed"}]
    
    result = complete_task("task-123")
    
    assert result is not None
    assert result[0]["status"] == "Completed"

def test_save_update(mock_supabase, mocker, caplog):
    caplog.set_level("CRITICAL")
    # Mock calculate_rag inside rag.py since save_update imports it
    mocker.patch('rag.calculate_rag', return_value=("GREEN", ""))
    
    mock_task_exec = mock_supabase.table("tasks").select().eq().execute
    mock_task_exec.return_value.data = [{"created_at": "2026-01-01T00:00:00+00:00", "deadline": "2026-02-01T00:00:00+00:00"}]
    
    mock_update_exec = mock_supabase.table("updates").insert().execute
    mock_update_exec.return_value.data = [{"id": "update-123"}]
    
    # Needs to mock update as well
    mock_supabase.table("tasks").update().eq().execute.return_value.data = []
    
    result = save_update("task-123", 50, "No blocker", [], "emp-123")
    assert result is not None

def test_archive_restore_task(mock_supabase):
    mock_execute_archive = mock_supabase.table("tasks").update().eq().execute
    mock_execute_archive.return_value.data = [{"id": "task-1", "is_archived": True}]
    
    result_archive = archive_task("task-1")
    assert result_archive[0]["is_archived"] is True
    
    mock_execute_restore = mock_supabase.table("tasks").update().eq().execute
    mock_execute_restore.return_value.data = [{"id": "task-1", "is_archived": False}]
    
    result_restore = restore_task("task-1")
    assert result_restore[0]["is_archived"] is False

def test_delete_task(mock_supabase):
    mock_execute = mock_supabase.table("tasks").delete().eq().execute
    mock_execute.return_value.data = [{"id": "task-1"}]
    
    result = delete_task("task-1")
    assert result[0]["id"] == "task-1"

def test_set_task_reminder(mock_supabase):
    time_str = datetime.now().isoformat()
    mock_execute = mock_supabase.table("tasks").update().eq().execute
    mock_execute.return_value.data = [{"id": "task-1", "reminder_time": time_str}]
    
    result = set_task_reminder("task-1", time_str)
    assert result[0]["reminder_time"] == time_str

def test_bulk_update_tasks(mock_supabase):
    mock_execute = mock_supabase.table("tasks").update().in_().execute
    mock_execute.return_value.data = [{"id": "task-1"}, {"id": "task-2"}]
    
    result = bulk_update_tasks(["task-1", "task-2"], {"status": "Completed"})
    assert len(result) == 2

@pytest.mark.asyncio
async def test_perform_update_with_note(mocker):
    mocker.patch("core.intent_handlers.get_context", return_value={})
    mocker.patch("core.intent_handlers.get_all_tasks", return_value=[{"id": "t-1", "name": "Test Task", "progress": 50}])
    mocker.patch("core.intent_handlers.resolve_task_from_list", return_value={"id": "t-1", "name": "Test Task", "progress": 50})
    mocker.patch("core.intent_handlers._resolve_user", return_value={"id": "u-1"})
    mocker.patch("core.intent_handlers.update_context")
    mocker.patch("core.intent_handlers.set_state")
    mock_save_update = mocker.patch("core.intent_handlers.save_update")

    mock_send = mocker.AsyncMock()

    from core.intent_handlers import perform_update
    await perform_update("Test Task", "100", "user-123", mock_send, images=["img1.png"], note="Completed successfully")

    mock_save_update.assert_called_once_with("t-1", 100, "None", ["img1.png"], "u-1", new_deadline=None, note="Completed successfully")
    mock_send.assert_called_once()
