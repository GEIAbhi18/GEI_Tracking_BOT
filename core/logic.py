import logging
from core.update_engine import process_update_message

async def process_user_message(user_id: str, text: str, images: list = None, send_reply_func=None) -> str:
    """
    Shared logic used by both Telegram and WhatsApp bots.
    If send_reply_func is provided (like in Telegram), it will use that for realtime async replies.
    If not provided (like in WhatsApp), it will accumulate the responses and return them as a string.
    """
    responses = []
    
    # Dummy reply function to aggregate responses if one isn't provided
    async def default_reply(reply_text: str = None, document: str = None, target_user_id: int = None):
        if reply_text:
            responses.append(reply_text)
        if document:
            responses.append(f"📄 [Document available: {document}]")
            
    reply_cb = send_reply_func if send_reply_func else default_reply
    _images = images if images else []
    
    try:
        await process_update_message(text=text, user_id=int(user_id), images=_images, send_reply_func=reply_cb)
    except Exception as e:
        logging.exception(f"Error processing message: {e}")
        if not send_reply_func:
            responses.append(f"Sorry, an error occurred while processing your request.")
            
    # Combine collected responses for webhook-style return
    return "\n".join(responses)
