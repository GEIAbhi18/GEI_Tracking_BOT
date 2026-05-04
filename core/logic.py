import logging
from core.update_engine import process_update_message

async def process_user_message(user_id: str, text: str, images: list = None, send_reply_func=None) -> str:
    """
    Shared logic used by both Telegram and WhatsApp bots.
    If send_reply_func is provided (like in Telegram), it will use that for realtime async replies.
    If not provided (like in WhatsApp), it will accumulate the responses and return them as a string.
    """
    responses = []
    document_paths = []

    # Default reply accumulator used when no send_reply_func is provided (e.g. WhatsApp webhook path)
    # Parameter names MUST match what intent_handlers call: text= and document=
    async def default_reply(text: str = None, document: str = None, target_user_id: int = None):
        if text:
            responses.append(text)
        if document:
            document_paths.append(document)   # collected separately so WhatsApp can upload it

    reply_cb = send_reply_func if send_reply_func else default_reply
    _images = images if images else []

    try:
        await process_update_message(text=text, user_id=int(user_id), images=_images, send_reply_func=reply_cb)
    except Exception as e:
        logging.exception(f"Error processing message: {e}")
        if not send_reply_func:
            responses.append("Sorry, an error occurred while processing your request.")

    # Combine collected responses for webhook-style return
    # Also attach document paths so the WhatsApp layer can access them
    result = "\n".join(responses)
    # Store document paths as a module-level list so WhatsApp webhook can pick them up
    # We attach them to the coroutine frame via a well-known attribute
    process_user_message._last_documents = document_paths
    return result
