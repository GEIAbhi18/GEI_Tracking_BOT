import pytest
from tasks.service import create_followup_task

def test_type_of_supabase(mock_supabase):
    import tasks.service
    print("\ntasks.service.supabase type:", type(tasks.service.supabase))
    print("tasks.service.supabase:", tasks.service.supabase)
    print("Is it mock?", hasattr(tasks.service.supabase, 'assert_called'))
    
    import db
    print("db.supabase type:", type(db.supabase))
    print("db.supabase:", db.supabase)
    print("db.supabase._init():", db.supabase._init())

