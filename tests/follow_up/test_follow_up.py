import pytest
from tasks.service import create_followup_task
from tests.fixtures.factories import create_mock_task, create_mock_user

def test_create_followup_task(mock_supabase, mocker):
    """Test follow up task creation."""
    # Mock get_task_by_id
    mocker.patch("tasks.service.get_task_by_id", return_value={"id": "parent-1", "title": "Old Task", "task_type": "PERSONAL", "priority": "High", "assigned_to": "user-2"})
    # Mock validate_task_creation
    mocker.patch("tasks.service.validate_task_creation", return_value=(True, ""))
    # Mock supabase for assignment validation
    mock_supabase.table("users").select().eq().execute().data = [{"id": "user-2", "team_id": None}]
    mocker.patch("tasks.service.validate_assignment", return_value=(True, ""))
    
    # Mock create_task
    mocker.patch("tasks.service.create_task", return_value={"id": "followup-1"})
    # Mock timeline
    mock_timeline = mocker.patch("tasks.service.add_timeline_event")
    
    current_user = {"id": "user-1", "team_id": None}
    
    task = create_followup_task(current_user, "parent-1")
    
    assert task is not None
    assert task["id"] == "followup-1"
    
    mock_timeline.assert_called_once()

def test_create_followup_task_invalid_parent(mocker):
    """Test follow up task creation fails if parent doesn't exist."""
    mocker.patch("tasks.service.get_task_by_id", return_value=None)
    
    current_user = {"id": "user-1", "team_id": None}
    
    with pytest.raises(ValueError, match="Parent task not found."):
        create_followup_task(current_user, "parent-1")
