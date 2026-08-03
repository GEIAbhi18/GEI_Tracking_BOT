import pytest
from db import get_user_by_name
from whatsapp.ux import clean_phone_number

def test_clean_phone_number():
    assert clean_phone_number("+919996221554") == "919996221554"
    assert clean_phone_number("9996221554") == "919996221554"
    assert clean_phone_number("919996221554") == "919996221554"
    assert clean_phone_number("+91 999 622 1554") == "919996221554"
    assert clean_phone_number("") == ""

def test_get_user_by_name_vikas_alias(mocker):
    mock_supabase = mocker.patch("db.supabase")
    
    first_res = mocker.MagicMock()
    first_res.data = []
    second_res = mocker.MagicMock()
    second_res.data = [{"id": "vikas-uuid", "name": "Vikash", "whatsapp_number": "919996221554"}]
    
    execute_mock = mocker.MagicMock()
    execute_mock.execute.side_effect = [first_res, second_res]
    mock_supabase.table.return_value.select.return_value.ilike.return_value = execute_mock

    user = get_user_by_name("Vikas")
    assert user is not None
    assert user["name"] == "Vikash"
