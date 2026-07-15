import pytest
from unittest.mock import MagicMock
import db

def test_mock_supabase(mocker):
    mock_client = MagicMock()
    mocker.patch('db._LazySupabase._init', return_value=mock_client)
    
    from tasks.service import supabase as service_supabase
    
    print("db.supabase:", db.supabase)
    print("service_supabase:", service_supabase)
    print("service_supabase._init():", service_supabase._init())
    print("service_supabase.table:", service_supabase.table)
    print("service_supabase.table('users'):", service_supabase.table('users'))
    
