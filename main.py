import logging
from bot import application
from scheduler import start_scheduler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

if __name__ == '__main__':
    logging.info("Starting GEI Tracking Bot...")
    start_scheduler(application)
    application.run_polling()
