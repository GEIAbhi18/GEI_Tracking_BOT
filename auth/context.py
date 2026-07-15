import contextvars

# Stores a dictionary representing the authenticated user session for the current thread/async task
current_user = contextvars.ContextVar("current_user", default=None)

def get_current_user():
    """Retrieve the current authenticated user dictionary."""
    return current_user.get()

def set_current_user(user_dict):
    """Set the current authenticated user dictionary."""
    current_user.set(user_dict)
