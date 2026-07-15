import logging
from db import supabase

logger = logging.getLogger(__name__)

def create_team(name: str):
    """Create a new team in the database."""
    try:
        response = supabase.table("teams").insert({"name": name}).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error creating team {name}: {e}")
        raise

def get_all_teams():
    """Fetch all teams from the database."""
    try:
        response = supabase.table("teams").select("*").order("name").execute()
        return response.data
    except Exception as e:
        logger.error(f"Error fetching teams: {e}")
        raise

def get_team_by_id(team_id: str):
    """Fetch a single team by its ID."""
    try:
        response = supabase.table("teams").select("*").eq("id", team_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error fetching team {team_id}: {e}")
        raise

def update_team(team_id: str, new_name: str):
    """Update an existing team's name."""
    try:
        response = supabase.table("teams").update({"name": new_name}).eq("id", team_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error updating team {team_id}: {e}")
        raise

def delete_team(team_id: str):
    """
    Delete a team by its ID. 
    Foreign key constraints ON DELETE SET NULL on users and tasks will 
    automatically detach users and tasks from this team without deleting them.
    """
    try:
        response = supabase.table("teams").delete().eq("id", team_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error deleting team {team_id}: {e}")
        raise
