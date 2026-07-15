import pytest
from notifications.dispatcher import dispatch_task_event, queue_notification
from db import supabase

def test_dispatch_task_event_assignment(mock_supabase, mocker):
    """Test that assignment event only queues notification for assignee."""
    mock_execute = mock_supabase.table("tasks").select().eq().execute
    
    mock_execute.return_value.data = [{
        "id": "task-1",
        "title": "Test Task",
        "created_by": "user-1",
        "assigned_to": "user-2",
        "created_by_user": {"id": "user-1", "name": "Creator"},
        "assigned_to_user": {"id": "user-2", "name": "Assignee"},
        "projects": {"name": "Project X"}
    }]
    
    mock_queue = mocker.patch("notifications.dispatcher.queue_notification")
    
    dispatch_task_event("task-1", "Assigned")
    
    # Assert queued for assignee (user-2)
    mock_queue.assert_called_once()
    args, _ = mock_queue.call_args
    assert args[0] == "user-2"
    assert args[2] == "Assigned"

def test_dispatch_task_event_creator_updates(mock_supabase, mocker):
    """Test that task updates like Completed only notify the creator, not assignee."""
    mock_execute = mock_supabase.table("tasks").select().eq().execute
    
    mock_execute.return_value.data = [{
        "id": "task-1",
        "title": "Test Task",
        "created_by": "user-1",
        "assigned_to": "user-2",
        "created_by_user": {"id": "user-1", "name": "Creator"},
        "assigned_to_user": {"id": "user-2", "name": "Assignee"},
        "projects": {"name": "Project X"}
    }]
    
    mock_queue = mocker.patch("notifications.dispatcher.queue_notification")
    
    dispatch_task_event("task-1", "Completed")
    
    # Assert queued for creator (user-1)
    mock_queue.assert_called_once()
    args, _ = mock_queue.call_args
    assert args[0] == "user-1"
    assert args[2] == "Completed"

def test_dispatch_task_event_same_user(mock_supabase, mocker):
    """Test that creator does not get notified if they are also the assignee."""
    mock_execute = mock_supabase.table("tasks").select().eq().execute
    
    mock_execute.return_value.data = [{
        "id": "task-1",
        "title": "Test Task",
        "created_by": "user-1",
        "assigned_to": "user-1",
        "created_by_user": {"id": "user-1", "name": "Creator"},
        "assigned_to_user": {"id": "user-1", "name": "Assignee"}
    }]
    
    mock_queue = mocker.patch("notifications.dispatcher.queue_notification")
    
    dispatch_task_event("task-1", "Completed")
    
    # Should not queue notification for self
    mock_queue.assert_not_called()

def test_queue_notification(mock_supabase):
    mock_insert = mock_supabase.table("notifications").insert().execute
    
    queue_notification("user-1", "task-1", "Assigned", {"task_title": "Title", "project_name": "P", "creator_name": "C", "assignee_name": "A", "due_date": "D"})
    
    mock_insert.assert_called_once()
