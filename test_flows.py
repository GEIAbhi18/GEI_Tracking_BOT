import os
import sys
import asyncio
from unittest.mock import patch
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Test")

# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Mock UX functions to prevent actual WhatsApp messages from being sent
def mock_send_text(to, body):
    logger.info(f"MOCK [send_text] to {to}: {body}")
    return True

def mock_send_interactive_buttons(to, body, buttons):
    logger.info(f"MOCK [send_interactive_buttons] to {to}: {body} | Buttons: {buttons}")
    return True

def mock_send_list_message(to, body, button_text, sections):
    logger.info(f"MOCK [send_list_message] to {to}: {body} | Button: {button_text} | Sections: {sections}")
    return True

# Apply patches
patcher_text = patch('whatsapp.ux.send_text', side_effect=mock_send_text)
patcher_btn = patch('whatsapp.ux.send_interactive_buttons', side_effect=mock_send_interactive_buttons)
patcher_list = patch('whatsapp.ux.send_list_message', side_effect=mock_send_list_message)

patcher_text.start()
patcher_btn.start()
patcher_list.start()

from whatsapp.whatsapp_webhook import _handle_interactive
from db import supabase

DEVELOPER_PHONE = "917717754421"  # Abhijeet's phone number (Developer)

def simulate_interactive(sender: str, i_type: str, action_id: str):
    logger.info(f"\n--- Simulating Interactive: {i_type} -> {action_id} ---")
    message = {
        "interactive": {
            "type": i_type
        }
    }
    if i_type == "button_reply":
        message["interactive"]["button_reply"] = {"id": action_id}
    elif i_type == "list_reply":
        message["interactive"]["list_reply"] = {"id": action_id}
        
    _handle_interactive(sender, message)

async def run_tests():
    try:
        # 1. Test Admin Switch to Guest
        simulate_interactive(DEVELOPER_PHONE, "list_reply", "admin_switch_guest")
        
        # Verify DB state for Guest mode
        res = supabase.table("wa_task_states").select("*").eq("whatsapp_number", DEVELOPER_PHONE).execute()
        logger.info(f"wa_task_states for {DEVELOPER_PHONE}: {res.data}")
        
        # 2. Test Guest Menu (should now synthesize guest user)
        simulate_interactive(DEVELOPER_PHONE, "list_reply", "guest_office")
        
        # 3. Test Admin Switch back to Kanav
        simulate_interactive(DEVELOPER_PHONE, "list_reply", "admin_switch_kanav")
        
        # Verify DB state for Kanav
        res = supabase.table("wa_task_states").select("*").eq("whatsapp_number", DEVELOPER_PHONE).execute()
        logger.info(f"wa_task_states for {DEVELOPER_PHONE}: {res.data}")
        
        # 4. Test Create Personal Task
        simulate_interactive(DEVELOPER_PHONE, "list_reply", "menu_create_task")
        simulate_interactive(DEVELOPER_PHONE, "button_reply", "create_task_personal")
        
        # Verify state
        res = supabase.table("wa_task_states").select("*").eq("whatsapp_number", DEVELOPER_PHONE).execute()
        logger.info(f"wa_task_states for {DEVELOPER_PHONE}: {res.data}")

        # 5. Clean up testing state
        supabase.table("wa_task_states").delete().eq("whatsapp_number", DEVELOPER_PHONE).execute()
        logger.info("\n--- ALL TESTS COMPLETED SUCCESSFULLY ---")

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
    finally:
        patcher_text.stop()
        patcher_btn.stop()
        patcher_list.stop()

if __name__ == "__main__":
    asyncio.run(run_tests())
