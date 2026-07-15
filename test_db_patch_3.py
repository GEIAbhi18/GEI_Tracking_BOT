import pytest

def test_type(mock_supabase):
    from tasks.service import supabase as svc_supabase
    print("\nSVC SUPABASE TYPE:", type(svc_supabase))
    print("\nSVC SUPABASE.table TYPE:", type(svc_supabase.table))
    print("\nSVC SUPABASE.table('users').select TYPE:", type(svc_supabase.table('users').select))

