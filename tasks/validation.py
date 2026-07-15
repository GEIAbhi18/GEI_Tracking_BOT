def validate_task_creation(data: dict) -> tuple:
    """Validates input data for creating a task."""
    title = data.get("title")
    if not title or not isinstance(title, str) or len(title.strip()) < 3:
        return False, "Task title must be at least 3 characters long."
        
    task_type = data.get("task_type")
    if task_type not in ["TEAM", "PERSONAL"]:
        return False, "Invalid task_type. Must be TEAM or PERSONAL."
        
    priority = data.get("priority", "Medium")
    if priority not in ["Critical", "High", "Medium", "Low"]:
        return False, "Invalid priority level."
        
    return True, None

def validate_assignment(current_user: dict, target_user: dict) -> tuple:
    """Validates if current_user can assign a task to target_user."""
    if not target_user:
        return False, "Target user does not exist."
        
    # Developers and Directors can assign to anyone
    if current_user.get("role") in ["Developer", "Director"]:
        return True, None
        
    # Employees can only assign within their own team
    if current_user.get("team_id") != target_user.get("team_id"):
        return False, "You can only assign tasks to members of your own team."
        
    return True, None

def validate_status_transition(current_status: str, new_status: str) -> tuple:
    """Validates the state machine for task status changes."""
    valid_transitions = {
        "Pending": ["Accepted", "Closed"],
        "Accepted": ["In Progress", "Pending", "Closed"],
        "In Progress": ["Completed", "Pending", "Closed"],
        "Completed": ["Closed", "Reopened"],
        "Closed": ["Reopened"],
        "Reopened": ["In Progress", "Closed"]
    }
    
    if new_status not in valid_transitions.get(current_status, []):
        return False, f"Cannot transition task from {current_status} to {new_status}."
        
    return True, None
