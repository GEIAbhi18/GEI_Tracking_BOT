from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler
from config import TELEGRAM_BOT_TOKEN
import logging
from handlers import start, handle_employee_update, test_reminder, test_update, test_report, view_tickets, raise_ticket, reply_ticket, trigger_drilldown

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("test_reminder", test_reminder))
application.add_handler(CommandHandler("test_update", test_update))
application.add_handler(CommandHandler("test_6pm", test_report))
application.add_handler(CommandHandler("test_report", test_report))

application.add_handler(CommandHandler("view_tickets", view_tickets))
application.add_handler(CommandHandler("raise_ticket", raise_ticket))
application.add_handler(CommandHandler("reply_ticket", reply_ticket))

from telegram.ext import MessageHandler, filters
application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_employee_update))
# Handle photo uploads with caption
application.add_handler(MessageHandler(filters.PHOTO, handle_employee_update))

application.add_handler(CallbackQueryHandler(trigger_drilldown))
