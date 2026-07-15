import pytest
from auth.middleware import authenticate_whatsapp_request
from auth.context import get_current_user
from tests.fixtures.factories import create_mock_user

def test_authenticate_whatsapp_request_existing_user(mock_supabase):
    """Test authenticating an existing user sets the context correctly."""
    mock_user = create_mock_user(role="employee", whatsapp_number="1234567890")
    
    # Configure mock Supabase response for db.get_or_create_user_by_whatsapp
    # get_or_create_user_by_whatsapp calls: supabase.table("users").select("*").eq(...).execute()
    mock_execute = mock_supabase.table("users").select().eq().execute
    mock_execute.return_value.data = [mock_user]
    
    auth_user = authenticate_whatsapp_request("1234567890")
    
    assert auth_user is not None
    assert auth_user["whatsapp_number"] == "1234567890"
    assert auth_user["role"] == "employee"
    assert "permissions" in auth_user
    
    # Check context
    context_user = get_current_user()
    assert context_user is not None
    assert context_user["id"] == auth_user["id"]

def test_authenticate_whatsapp_request_new_user(mock_supabase):
    """Test a new unknown number creates a Guest user."""
    # First select returns empty, then insert returns the new user
    mock_table = mock_supabase.table("users")
    
    mock_execute_select = mock_table.select().eq().execute
    mock_execute_select.return_value.data = []
    
    mock_execute_insert = mock_table.insert().execute
    mock_guest_user = create_mock_user(role="Guest", whatsapp_number="9999999999")
    mock_execute_insert.return_value.data = [mock_guest_user]
    
    auth_user = authenticate_whatsapp_request("9999999999")
    
    assert auth_user is not None
    assert auth_user["role"] == "Guest"
    assert "permissions" in auth_user
    assert "CREATE_TASK" not in auth_user["permissions"] # Guests can't create tasks
    
def test_authenticate_whatsapp_request_db_error(mock_supabase, caplog):
    """Test handling of DB errors during auth."""
    caplog.set_level("CRITICAL")
    mock_execute = mock_supabase.table("users").select().eq().execute
    mock_execute.side_effect = Exception("DB Connection Error")
    
    auth_user = authenticate_whatsapp_request("error_number")
    
    assert auth_user is None
