# GEI Tracking Bot MVP

A Telegram MVP to manage tracking, deadlines, updates, and RAG statuses. 

## Features
- **NLP Update Flow**: Employee inputs text + progress + blockers roughly, bot auto-extracts info.
- **RAG System**: Automated color rating based on progress against time, blockers, and missed updates. Project summary rolls up task statuses.
- **Non-response Logic**: Identifies skipped updates and alerts Director at 6PM.
- **Ticket System**: Direct communication inside Telegram between Employee and Director linked to projects.
- **Daily Reminders**: Scheduled pings to Asif to update by 5PM.
- **6PM Summary Report**: Auto-dispatch of Project-RAG summary to Kanav.

## Installation

1. Create a `virtualenv` and `source` it.
2. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in credentials:
   - `TELEGRAM_BOT_TOKEN`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `EMPLOYEE_CHAT_ID`
   - `DIRECTOR_CHAT_ID`
4. Apply the `supabase_schema.sql` found in the root of the project to your Supabase SQL editor.
5. Run the bot:
   ```bash
   python main.py
   ```
