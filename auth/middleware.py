import logging
from auth.context import set_current_user
from auth.permissions import get_permissions_for_role, Role
from db import get_or_create_user_by_whatsapp

logger = logging.getLogger(__name__)

def authenticate_whatsapp_request(sender_phone: str):
    """
    Middleware function that authenticates the incoming WhatsApp sender.
    It fetches the user from the DB. If they don't exist, it creates a Guest user.
    It then resolves their permissions and sets them into the current thread context.
    
    Returns the authenticated user dict.
    """
    try:
        # DB will automatically create them as Guest if they do not exist
        user = get_or_create_user_by_whatsapp(sender_phone)
        
        if not user:
            logger.error(f"Failed to authenticate or create user for {sender_phone}")
            return None
            
        # Resolve permissions
        user_role = user.get("role", Role.GUEST.value)
        permissions = get_permissions_for_role(user_role)
        
        # Attach permissions to user object
        user["permissions"] = permissions
        
        # Set into context variable for downstream guards
        set_current_user(user)
        
        logger.info(f"Authenticated {sender_phone} as {user_role}")
        return user
        
    except Exception as e:
        logger.error(f"Error in authentication middleware for {sender_phone}: {e}")
        return None
