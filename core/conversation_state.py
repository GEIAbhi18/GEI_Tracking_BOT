import time

_states = {}
TIMEOUT_SECONDS = 600 # 10 minutes

def get_state(user_id):
    """Retrieve the current state for a user, checking for timeout."""
    state_obj = _states.get(user_id)
    if not state_obj:
        return None
    
    # Check for timeout
    if time.time() - state_obj.get("timestamp", 0) > TIMEOUT_SECONDS:
        clear_state(user_id)
        return None
        
    return state_obj.get("state")

def set_state(user_id, state):
    """Store the state for a user with a timestamp."""
    _states[user_id] = {
        "state": state,
        "timestamp": time.time()
    }

def clear_state(user_id):
    """Remove the state for a user."""
    if user_id in _states:
        del _states[user_id]

