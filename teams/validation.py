import re
from typing import Tuple, Optional

def validate_team_name(name: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validates a team name before insertion or update.
    Returns (is_valid, sanitized_name, error_message).
    """
    if not name or not isinstance(name, str):
        return False, None, "Team name must be a valid string."
        
    sanitized = name.strip()
    
    if len(sanitized) < 2:
        return False, None, "Team name must be at least 2 characters long."
        
    if len(sanitized) > 50:
        return False, None, "Team name cannot exceed 50 characters."
        
    # Prevent completely weird characters (allow alphanumeric, spaces, and basic punctuation)
    if not re.match(r"^[a-zA-Z0-9\s\-_&]+$", sanitized):
        return False, None, "Team name contains invalid characters."
        
    return True, sanitized, None
