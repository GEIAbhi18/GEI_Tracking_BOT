import logging
from db import supabase

logger = logging.getLogger(__name__)

def get_dashboard_stats(timeframe: str = 'all_time'):
    try:
        response = supabase.rpc('get_dashboard_stats', {'timeframe': timeframe}).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {e}")
        return None

def get_team_reports(timeframe: str = 'all_time'):
    try:
        response = supabase.rpc('get_team_reports', {'timeframe': timeframe}).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error fetching team reports: {e}")
        return []

def get_employee_reports(timeframe: str = 'all_time'):
    try:
        response = supabase.rpc('get_employee_reports', {'timeframe': timeframe}).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error fetching employee reports: {e}")
        return []

def get_most_active_employee(timeframe: str = 'all_time'):
    try:
        response = supabase.rpc('get_most_active_employee', {'timeframe': timeframe}).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error fetching most active employee: {e}")
        return None

def get_task_timeline(task_id: str):
    try:
        response = supabase.rpc('get_task_timeline', {'target_task_id': task_id}).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error fetching task timeline: {e}")
        return []
