import pytest
from unittest.mock import MagicMock
import asyncio



@pytest.fixture
def mock_supabase(mocker):
    """
    Mock Supabase client.
    We patch both the LazySupabase wrapper and the direct client to ensure
    no real network requests are made during testing.
    """
    mock_client = MagicMock()
    
    table_mocks = {}
    
    # Common table mock behavior
    def mock_table(table_name):
        if table_name in table_mocks:
            return table_mocks[table_name]
            
        table_mock = MagicMock()
        # Allows chaining like: supabase.table("users").select("*").eq(...).execute()
        table_mock.select.return_value = table_mock
        table_mock.insert.return_value = table_mock
        table_mock.update.return_value = table_mock
        table_mock.delete.return_value = table_mock
        table_mock.eq.return_value = table_mock
        table_mock.neq.return_value = table_mock
        table_mock.ilike.return_value = table_mock
        table_mock.in_.return_value = table_mock
        table_mock.gte.return_value = table_mock
        table_mock.lte.return_value = table_mock
        table_mock.order.return_value = table_mock
        table_mock.limit.return_value = table_mock
        
        # Default execute returns an empty data list
        execute_mock = MagicMock()
        execute_mock.data = []
        table_mock.execute.return_value = execute_mock
        
        table_mocks[table_name] = table_mock
        return table_mock

    mock_client.table.side_effect = mock_table
    mock_client.rpc.return_value = MagicMock(execute=MagicMock(return_value=MagicMock(data=[])))
    
    # Patch the global supabase instance init in db.py
    mocker.patch('db._LazySupabase._init', return_value=mock_client)
    mocker.patch('db.supabase', mock_client)
    
    return mock_client

@pytest.fixture
def mock_requests(mocker):
    """Mock the requests library for webhooks, file downloads, etc."""
    return mocker.patch('requests.get')

@pytest.fixture
def mock_post_requests(mocker):
    return mocker.patch('requests.post')
