import pytest
from db import get_all_tasks
from tests.fixtures.factories import create_mock_task

def test_personal_task_isolation_creator(mock_supabase):
    """Test that a personal task is returned if the user is the creator."""
    mock_execute = mock_supabase.table("tasks").select().execute
    
    mock_task_personal = create_mock_task("project-1", assigned_to_id="user-2", task_type="PERSONAL")
    mock_task_personal["created_by"] = "user-1"
    
    mock_execute.return_value.data = [mock_task_personal]
    
    # User 1 requests tasks (they are the creator)
    tasks = get_all_tasks(user_id="user-1")
    assert len(tasks) == 1
    
    # User 2 requests tasks (they are assigned to it)
    tasks = get_all_tasks(user_id="user-2")
    assert len(tasks) == 1
    
def test_personal_task_isolation_stranger(mock_supabase):
    """Test that a personal task is hidden from users who didn't create it and aren't assigned to it."""
    mock_execute = mock_supabase.table("tasks").select().execute
    
    mock_task_personal = create_mock_task("project-1", assigned_to_id="user-2", task_type="PERSONAL")
    mock_task_personal["created_by"] = "user-1"
    
    mock_execute.return_value.data = [mock_task_personal]
    
    # User 3 requests tasks (stranger)
    tasks = get_all_tasks(user_id="user-3")
    assert len(tasks) == 0
    
def test_project_task_visible_to_all(mock_supabase):
    """Test that a project task is visible even to strangers."""
    mock_execute = mock_supabase.table("tasks").select().execute
    
    mock_task_project = create_mock_task("project-1", assigned_to_id="user-2", task_type="PROJECT")
    mock_task_project["created_by"] = "user-1"
    
    mock_execute.return_value.data = [mock_task_project]
    
    tasks = get_all_tasks(user_id="user-3")
    assert len(tasks) == 1
