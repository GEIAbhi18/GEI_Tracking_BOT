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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command to welcome the user."""
    welcome_message = "Welcome to the GEI Tracking Bot! I am ready to help you with task updates, blockers, and queries."
    await update.message.reply_text(welcome_message)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler acting as an input/output layer for the centralized backend."""
    user_message = update.message.text or update.message.caption or ""
    user_id = update.effective_user.id
    
    # Extract images if a photo was uploaded
    images = []
    if update.message.photo:
        # Get the highest resolution photo
        photo_file = await update.message.photo[-1].get_file()
        images.append(photo_file.file_path)
    
    # Define how the backend should send replies back to this Telegram user
    async def reply_function(text: str):
        await update.message.reply_text(text)
        
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

# Initialize the application
application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

# Add handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
application.add_handler(MessageHandler(filters.PHOTO, handle_message))

if __name__ == '__main__':
    logging.info("Starting GEI Telegram Bot in polling mode...")
    application.run_polling()
