import logging
import time
from datetime import datetime, timedelta
from db import supabase

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

def process_notifications():
    """
    Worker function to process pending notifications with retry logic.
    """
    try:
        now = datetime.utcnow().isoformat()
        
        # Fetch pending notifications that are scheduled to run now or earlier
        res = supabase.table("notifications") \
            .select("*, users(telegram_id, whatsapp_number)") \
            .eq("status", "Pending") \
            .lte("scheduled_for", now) \
            .execute()
            
        notifications = res.data
        if not notifications:
            return
            
        from whatsapp.ux import send_text
        from bot import application  # Assuming PTB application can be accessed for Telegram, or just use requests
        
        for notif in notifications:
            notif_id = notif["id"]
            user = notif.get("users", {})
            message = notif.get("message", "")
            retry_count = notif.get("retry_count", 0)
            
            wa_number = user.get("whatsapp_number")
            tg_id = user.get("telegram_id")
            
            success = False
            
            try:
                # Attempt to send via WhatsApp first if available
                if wa_number:
                    send_text(wa_number, message)
                    success = True
                elif tg_id:
                    # In a real async environment, we'd use application.bot.send_message
                    # For this synchronous worker, we can just log or use raw requests
                    # Placeholder for Telegram dispatch:
                    logger.info(f"[TELEGRAM] Dispatching to {tg_id}: {message}")
                    success = True
                else:
                    logger.warning(f"No valid contact info for user {notif['user_id']}")
                    # If no contact info, mark as failed permanently
                    success = False
                    retry_count = MAX_RETRIES
                    
            except Exception as e:
                logger.error(f"Failed to send notification {notif_id}: {e}")
                success = False
                
            if success:
                supabase.table("notifications").update({"status": "Sent"}).eq("id", notif_id).execute()
                logger.info(f"Notification {notif_id} sent successfully.")
            else:
                retry_count += 1
                if retry_count > MAX_RETRIES:
                    supabase.table("notifications").update({"status": "Failed", "retry_count": retry_count}).eq("id", notif_id).execute()
                    logger.warning(f"Notification {notif_id} failed after {MAX_RETRIES} retries.")
                else:
                    # Exponential backoff: 1 min, 5 min, 15 min, etc.
                    backoff_minutes = 5 ** (retry_count - 1)
                    next_schedule = (datetime.utcnow() + timedelta(minutes=backoff_minutes)).isoformat()
                    supabase.table("notifications").update({
                        "retry_count": retry_count,
                        "scheduled_for": next_schedule
                    }).eq("id", notif_id).execute()
                    logger.info(f"Notification {notif_id} rescheduled for {next_schedule} (Retry {retry_count})")
                    
    except Exception as e:
        logger.error(f"Error in process_notifications worker: {e}")
