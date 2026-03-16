# In-memory context manager for conversational memory
import logging

logger = logging.getLogger(__name__)

_contexts = {}

def get_context(user_id):
    """Retrieve the conversation context for a user."""
    if user_id not in _contexts:
        _contexts[user_id] = {
            "recent_task_id": None,
            "recent_task_name": None,
            "messages": [],
            "last_command": None
        }
    return _contexts[user_id]

def update_context(user_id, task_id=None, task_name=None, message=None, last_command=None):
    """Update context with new data."""
    ctx = get_context(user_id)
    
    if task_id:
        ctx["recent_task_id"] = task_id
    if task_name:
        ctx["recent_task_name"] = task_name
    if last_command:
        ctx["last_command"] = last_command
        
    if message:
        ctx["messages"].append(message)
        # Limit to last 5 messages
        if len(ctx["messages"]) > 5:
            ctx["messages"] = ctx["messages"][-5:]
    
    _contexts[user_id] = ctx

def clear_context(user_id):
    """Clear context for a user."""
    if user_id in _contexts:
        del _contexts[user_id]
