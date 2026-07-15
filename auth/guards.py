import logging
from functools import wraps
from auth.context import get_current_user
from auth.permissions import Permission, Role

logger = logging.getLogger(__name__)

def require_permission(permission: Permission):
    """
    Decorator to protect a function so that it can only be executed if the 
    currently authenticated user has the specified permission.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                logger.warning(f"Unauthorized access attempt: No authenticated user context. Required: {permission.value}")
                return "🚫 You do not have permission to perform this action."
            
            # Developer has universal access
            if user.get("role") == Role.DEVELOPER.value:
                return func(*args, **kwargs)
                
            user_permissions = user.get("permissions", [])
            if permission.value not in [p.value for p in user_permissions]:
                logger.warning(f"Unauthorized access attempt by {user.get('whatsapp_number')}. Required: {permission.value}")
                return "🚫 You do not have permission to perform this action."
                
            return func(*args, **kwargs)
        
        # Also provide an async wrapper just in case the target is async
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                logger.warning(f"Unauthorized access attempt: No authenticated user context. Required: {permission.value}")
                return "🚫 You do not have permission to perform this action."
            
            # Developer has universal access
            if user.get("role") == Role.DEVELOPER.value:
                return await func(*args, **kwargs)
                
            user_permissions = user.get("permissions", [])
            if permission.value not in [p.value for p in user_permissions]:
                logger.warning(f"Unauthorized access attempt by {user.get('whatsapp_number')}. Required: {permission.value}")
                return "🚫 You do not have permission to perform this action."
                
            return await func(*args, **kwargs)

        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return wrapper
    return decorator
