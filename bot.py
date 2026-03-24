import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN
from core.update_engine import process_update_message

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
# You can switch these comments out while testing locally
# TEST_USER_ID = 123456789 # Asif Temp ID
# TEST_USER_ID = 987654321 # Kanav Temp ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command to welcome the user."""
    from db import get_user_by_telegram_id
    user_id = update.effective_user.id
    u_info = get_user_by_telegram_id(user_id)
    name = u_info['name'] if u_info else "there"
    welcome_message = f"Hi {name}, What can I help you with?"
    await update.message.reply_text(welcome_message)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = (update.message.text or update.message.caption or "").lstrip('/')
    user_id = update.effective_user.id
    
    # Extract images if a photo was uploaded
    images = []
    if update.message.photo:
        # Get the highest resolution photo
        photo_file = await update.message.photo[-1].get_file()
        images.append(photo_file.file_path)
    
    # Define how the backend should send replies back to this Telegram user
    async def reply_function(text: str = None, document: str = None, target_user_id: int = None):
        target = target_user_id if target_user_id else update.effective_chat.id
        
        # Safe HTML escaping for Telegram
        if text:
            import html, re
            text_html = html.escape(text)
            text_html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text_html)
            text_html = re.sub(r'\*(.+?)\*', r'<b>\1</b>', text_html)
        
        if document:
            with open(document, 'rb') as f:
                if text:
                    await context.bot.send_document(chat_id=target, document=f, caption=text_html, parse_mode='HTML')
                else:
                    await context.bot.send_document(chat_id=target, document=f)
        elif text:
            await context.bot.send_message(chat_id=target, text=text_html, parse_mode='HTML')
        
    try:
        # Call the existing shared backend
        await process_update_message(
            text=user_message,
            user_id=user_id,
            images=images,
            send_reply_func=reply_function
        )
    except Exception as e:
        logging.error(f"Error processing message for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Sorry, an error occurred while processing your request.")

async def send_daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    """Sends the daily PDF report to Kanav at 6 PM."""
    from core.intent_handlers import generate_pdf_report
    from db import supabase
    
    # Get Kanav's true telegram_id dynamically
    try:
        response = supabase.table("users").select("telegram_id").eq("name", "Kanav").execute()
        if not response.data or not response.data[0].get("telegram_id"):
            logging.error("Could not find Kanav's telegram_id in DB for 6PM job.")
            return
        target_user_id = response.data[0]["telegram_id"]
    except Exception as e:
        logging.error(f"Error fetching Kanav's telegram_id: {e}")
        return

    filepath = generate_pdf_report()
    
    with open(filepath, 'rb') as f:
        await context.bot.send_document(
            chat_id=target_user_id, 
            document=f, 
            caption="📊 Automated Daily Project Report (6:00 PM)"
        )

# Initialize the application
application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

# Add handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
application.add_handler(MessageHandler(filters.PHOTO, handle_message))

if __name__ == '__main__':
    import datetime
    import pytz
    
    logging.info("Starting GEI Telegram Bot in polling mode...")
    time.sleep(10)
    # Schedule the 6 PM daily report for Kanav
    tz = pytz.timezone('Asia/Kolkata')
    job_time = datetime.time(hour=18, minute=0, tzinfo=tz)
    application.job_queue.run_daily(send_daily_report_job, time=job_time)
    application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
