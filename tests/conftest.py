import os
import pytest
from unittest.mock import MagicMock
import asyncio

# Set test environment fallbacks early before module imports
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("WHATSAPP_FLOW_ID", "mock_flow_id")
os.environ.setdefault("WHATSAPP_FLOW_TEMPLATE_NAME", "gei_feedback_request")
os.environ.setdefault("META_ACCESS_TOKEN", "mock_token")
os.environ.setdefault("PHONE_NUMBER_ID", "mock_phone_id")



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


@pytest.fixture(autouse=True)
def prevent_whatsapp_messages_leak(monkeypatch):
    """
    Universal test safety fixture:
    1. Kanav is NOT a developer and must NEVER receive test messages.
    2. While testing, all messages redirect to Developer (917717754421) or are safely mocked.
    3. Prevents live Meta API calls during tests from reaching external recipients.
    """
    import os
    os.environ["TESTING"] = "1"
    os.environ.setdefault("WHATSAPP_FLOW_ID", "mock_flow_id")
    os.environ.setdefault("WHATSAPP_FLOW_TEMPLATE_NAME", "gei_feedback_request")
    os.environ.setdefault("META_ACCESS_TOKEN", "mock_token")
    os.environ.setdefault("PHONE_NUMBER_ID", "mock_phone_id")

    try:
        import feedback.config as f_cfg
        f_cfg.WHATSAPP_FLOW_ID = f_cfg.WHATSAPP_FLOW_ID or "mock_flow_id"
        f_cfg.WHATSAPP_FLOW_TEMPLATE_NAME = f_cfg.WHATSAPP_FLOW_TEMPLATE_NAME or "gei_feedback_request"
        f_cfg.META_ACCESS_TOKEN = f_cfg.META_ACCESS_TOKEN or "mock_token"
        f_cfg.PHONE_NUMBER_ID = f_cfg.PHONE_NUMBER_ID or "mock_phone_id"
    except Exception:
        pass
    try:
        import feedback.flow_sender as f_sender
        f_sender.WHATSAPP_FLOW_ID = f_sender.WHATSAPP_FLOW_ID or "mock_flow_id"
        f_sender.WHATSAPP_FLOW_TEMPLATE_NAME = f_sender.WHATSAPP_FLOW_TEMPLATE_NAME or "gei_feedback_request"
        f_sender.META_ACCESS_TOKEN = f_sender.META_ACCESS_TOKEN or "mock_token"
        f_sender.PHONE_NUMBER_ID = f_sender.PHONE_NUMBER_ID or "mock_phone_id"
    except Exception:
        pass

    from elara.config import KANAV_PHONE, DEVELOPER_PHONE
    from whatsapp import ux

    orig_post = ux._post_wa

    def safe_post_wa(payload: dict, *args, **kwargs) -> bool:
        to_phone = ux.clean_phone_number(payload.get("to"))
        # Strictly ensure Kanav never gets test messages
        if to_phone == ux.clean_phone_number(KANAV_PHONE):
            payload["to"] = DEVELOPER_PHONE
        # In automated testing, mock the network return to prevent spamming phones
        return True

    monkeypatch.setattr(ux, "_post_wa", safe_post_wa)
