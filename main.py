import logging
from bot import application
from scheduler import start_scheduler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

if __name__ == '__main__':
    logging.info("Starting GEI Tracking Bot in production mode...")
    
    # Start both scheduler systems to ensure all triggers (hourly & fixed) are active
    from core.reminder_scheduler import setup_reminder_scheduler
    start_scheduler(application)
    setup_reminder_scheduler(application)
    
    # Use drop_pending_updates to avoid processing old logic on restart
    application.run_polling(drop_pending_updates=True)
