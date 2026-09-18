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
    
    Impersonation logic:
      1. If user.role == Developer and user.impersonating_user_id is set → load that user
      2. If user.role == Developer and wa_task_states has GUEST_MODE → synthesize Guest
      3. Otherwise → use the real user
    
    Returns the authenticated user dict.
    """
    try:
        # DB will automatically create them as Guest if they do not exist
        user = get_or_create_user_by_whatsapp(sender_phone)
        
        if not user:
            logger.error(f"Failed to authenticate or create user for {sender_phone}")
            return None
            
        # --- Impersonation Logic for Developers ---
        if user.get("role") == "Developer":
            # Check 1: FK-based impersonation (real user target)
            if user.get("impersonating_user_id"):
                impersonated_id = user.get("impersonating_user_id")
                from db import get_user_by_id
                
                impersonated_user = get_user_by_id(impersonated_id)
                if impersonated_user:
                    logger.info(f"Developer {sender_phone} is impersonating {impersonated_user.get('name')}")
                    impersonated_user["whatsapp_number"] = sender_phone
                    impersonated_user["real_user_id"] = user["id"]
                    impersonated_user["original_role"] = "Developer"
                    user = impersonated_user
                else:
                    # Target user was deleted or invalid — clear the stale reference
                    logger.warning(f"Impersonated user {impersonated_id} not found, clearing stale reference.")
                    from db import supabase
                    supabase.table("users").update({"impersonating_user_id": None}).eq("id", user["id"]).execute()
            else:
                # Check 2: GUEST_MODE via wa_task_states (no FK needed)
                from db import supabase
                state_res = supabase.table("wa_task_states").select("action").eq("whatsapp_number", sender_phone).execute()
                if state_res.data and state_res.data[0].get("action") == "GUEST_MODE":
                    logger.info(f"Developer {sender_phone} is in GUEST_MODE")
                    user = {
                        "id": user["id"],  # keep real ID so we can switch back
                        "name": "Guest Tester",
                        "whatsapp_number": sender_phone,
                        "role": "Guest",
                        "real_user_id": user["id"],
                        "original_role": "Developer"
                    }

        # --- Chaitanya Temporary Tenant Override ---
        # Strictly treat Chaitanya as a Tenant only (Role.CLIENT).
        # Do not treat or identify Chaitanya as a Team Member anywhere in GEI_BOT flow.
        from clients.config import TREAT_CHAITANYA_AS_TENANT_ONLY, is_chaitanya
        if TREAT_CHAITANYA_AS_TENANT_ONLY and (
            is_chaitanya(sender_phone)
            or is_chaitanya(user.get("whatsapp_number"))
            or is_chaitanya(user.get("name"))
            or is_chaitanya(user.get("id"))
        ):
            user["role"] = Role.CLIENT.value
            user["department"] = None
            user["team_id"] = None
            user["permitted_buildings"] = []
            user["is_facilities_user"] = False
            user["is_elara_user"] = False

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
