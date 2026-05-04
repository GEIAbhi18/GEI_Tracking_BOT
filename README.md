# 🏗️ GEI Construction — Project Tracking Bot

> A dual-platform (Telegram + WhatsApp) AI-powered project management assistant built for GEI Construction. It replaces manual status calls and WhatsApp group chaos with a structured, role-aware bot that tracks tasks, flags blockers, generates reports, and manages task assignments — all through natural conversation.

---

## 📋 Table of Contents

- [What Problem Does This Solve?](#-what-problem-does-this-solve)
- [Who Uses It](#-who-uses-it)
- [How It Works — Plain English](#-how-it-works--plain-english)
- [Features at a Glance](#-features-at-a-glance)
- [Daily Workflow](#-daily-workflow)
- [WhatsApp Task Assignment Flow](#-whatsapp-task-assignment-flow-new)
- [All Commands & What They Do](#-all-commands--what-they-do)
- [RAG Status System](#-rag-status-system-explained)
- [Automated Schedules](#-automated-schedules)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Setup & Deployment](#-setup--deployment)
- [Environment Variables](#-environment-variables)
- [Database Schema](#-database-schema)

---

## 🤔 What Problem Does This Solve?

Construction site management involves:
- **Scattered updates** across WhatsApp groups
- **No accountability** when tasks slip
- **Manual status calls** between Kanav (director) and Asif (site manager)
- **No automatic escalation** when blockers aren't resolved
- **No paper trail** for task completions

**GEI Bot solves all of this** by being the single source of truth — Asif sends updates to the bot, Kanav sees automated reports, and everything is stored in a structured database.

---

## 👥 Who Uses It

| Person | Role | Platform | What They Do |
|--------|------|----------|-------------|
| **Kanav** | Director / Manager | Telegram + WhatsApp | Creates tasks, reviews reports, receives alerts |
| **Asif** | Site Manager / Employee | Telegram + WhatsApp | Sends daily updates, raises blockers, marks completions |

---

## 💬 How It Works — Plain English

### For Asif (Employee)
Asif opens Telegram and just **talks naturally** to the bot:

> *"Top Terrace waterproofing 40% done, material delay"*

The bot understands this, saves it to the database, and marks it with a RED/AMBER/GREEN health status. No forms, no spreadsheets.

He can also:
- Attach a **photo proof** when completing a task
- Raise a **support ticket** when something is blocked
- Ask to see his **pending tasks**
- Edit task dates if plans change

### For Kanav (Director)
Kanav gets **automated reports** without asking. Every evening at 6PM, the bot sends:
- A project-level colour-coded summary (🟢/🟡/🔴)
- A drill-down PDF report with every task's status
- Flags for tasks where Asif didn't respond

Kanav can also:
- Create new projects and tasks directly in chat
- Assign tasks to Asif → Asif gets a **WhatsApp notification with buttons** to Accept/Reject/Edit Date
- Ask the bot to ping Asif for an update
- View all blockers across all projects

---

## ✨ Features at a Glance

### 🧠 Natural Language Understanding
You don't need to type commands. The bot uses an LLM (Groq/Gemini) to understand plain English:
- *"complete task 3"* → marks task as done, asks for proof photo
- *"slope corrections is blocked due to rain"* → adds a blocker
- *"show overdue tasks"* → filters and lists tasks past deadline
- *"update waterproofing to 75%"* → saves progress

### 📊 RAG Health Tracking
Every task gets a colour based on actual vs expected progress:
- 🟢 **GREEN** — On track
- 🟡 **AMBER** — Slightly behind (< 75% of expected progress)
- 🔴 **RED** — Critically behind, or has blockers, or no update submitted
- ⚪ **NOT STARTED** — Task hasn't reached its planned start date

### 📱 Dual Platform
- **Telegram** — Primary interface for both Kanav and Asif (commands, updates, reports, photos)
- **WhatsApp** — Task assignment notifications with interactive buttons (Accept / Reject / Edit Date)

### 📄 Automated PDF Reports
Every day at 6PM, Kanav receives a professionally formatted PDF with:
- All projects and their tasks
- RAG status per task
- Progress %, planned vs actual dates
- Blocker details
- Proof photos

### 🎫 Ticket / Issue System
Asif can raise a support ticket for any blocked task. Kanav can reply and close tickets — all tracked in the database.

### ⏰ Automated Reminders
- **9AM daily** — Deadline alerts for tasks due today/tomorrow
- **5PM daily** — Reminder to Asif to submit his daily update
- **6PM daily** — Full project report sent to Kanav
- **Hourly** — Inactivity check; pings Asif if no update received

---

## 📅 Daily Workflow

```
9:00 AM  →  Bot sends deadline alerts to Asif
             "⚠️ Top Terrace - Waterproofing due tomorrow"

Throughout the day
         →  Asif sends updates:
             "slope test 60% done"
             "waterproofing complete" + [photo attached]

5:00 PM  →  Bot reminds Asif if no update sent yet

6:00 PM  →  Kanav receives:
             1. WhatsApp/Telegram summary (🟢🟡🔴 per project)
             2. Full PDF report with all task details
```

---

## 📲 WhatsApp Task Assignment Flow (NEW)

When **Kanav creates a task** through the bot, the system automatically:

**Step 1** — Sends an interactive WhatsApp message to Asif:
```
Kanav created a task for you:

📌 Task: Waterproofing layer 2
📂 Project: Top Terrace
📅 Planned completion date: 15 May 2026

Do you agree?
[✅ Accept]  [❌ Reject]  [📅 Edit Date]
```

**Step 2** — Kanav immediately gets:
```
✅ Task Created.
📩 Message sent to Asif for approval.
```

**Step 3** — Asif's response is handled:

| Asif clicks | What happens |
|-------------|-------------|
| ✅ Accept | DB updated, Kanav notified: *"Task accepted by Asif"* |
| ❌ Reject | Bot asks for reason → Kanav notified with reason |
| 📅 Edit Date | Bot asks for new date → deadline updated, Kanav notified |

> Only tasks created by **Kanav** trigger this flow. Tasks created by other users are simply saved to DB without WhatsApp messages.

---

## 🤖 All Commands & What They Do

### Employee (Asif) Commands

| Command / Message | What It Does |
|---|---|
| `update task` | Start guided task update flow |
| `"Top Terrace slope 40% done"` | Directly save a progress update via NLP |
| `complete task` | Mark a task as 100% complete, optionally attach proof photo |
| `add blocker` | Flag a task as blocked and describe the issue |
| `show tasks` / `list tasks` | View all assigned tasks with deadlines and progress |
| `edit date` | Change the start date or deadline of a task |
| `create note` | Add a note to any task |
| `raise ticket` | Open a support/issue ticket for a blocked task |
| `add image` | Attach a proof photo to any task |
| `/start` | Clear session and start fresh |
| `/help` | View available commands |

### Director (Kanav) Commands

| Command / Message | What It Does |
|---|---|
| `show tasks` | View all tasks for all team members, grouped by project |
| `create task` | Create a new task (triggers WhatsApp notification to Asif) |
| `create project` | Create a new project |
| `get report` | Generate and receive the PDF project report on demand |
| `show blockers` | View all currently blocked tasks across all projects |
| `ask asif` / `/ask_asif` | Send an immediate ping to Asif for an update |
| `edit date` | Edit start date or deadline of any task |
| `view tickets` | See all open support tickets raised by Asif |
| `Ticket 1. Working on it` | Reply to a specific ticket |
| `close Ticket 1` | Close a resolved ticket |
| `/start` | Clear session and start fresh |

### Natural Language Filter Examples (Both)

| You say | Bot understands |
|---|---|
| *"show overdue tasks"* | Tasks past their deadline |
| *"show tasks due this week"* | Tasks due in next 7 days |
| *"show blocked tasks"* | Tasks with active blockers |
| *"tasks completed this month"* | Completed tasks |
| *"what are Asif's tasks?"* | Tasks assigned to Asif |

---

## 🟢 RAG Status System Explained

RAG (Red / Amber / Green) is calculated automatically based on:

```
Expected Progress = (Days Elapsed / Total Duration) × 100%
Performance Ratio = Actual Progress / Expected Progress
```

| Performance Ratio | Status | Meaning |
|---|---|---|
| ≥ 0.75 (75%) | 🟢 GREEN | On track |
| 0.50 – 0.74 | 🟡 AMBER | Behind schedule |
| < 0.50 | 🔴 RED | Critically behind |
| Has blocker | 🔴 RED | Regardless of progress |
| No update submitted | 🔴 RED | Asif didn't respond |
| Before start date | ⚪ NOT STARTED | Task hasn't begun yet |

**Project-level RAG** is the worst of all its tasks — one RED task = RED project.

---

## ⏰ Automated Schedules

| Time | What Runs | Who Gets It |
|------|-----------|------------|
| 9:00 AM daily | Deadline alert for tasks due today/tomorrow | Asif |
| 5:00 PM daily | "Please submit your update" reminder | Asif |
| 6:00 PM daily | Project summary (🟢🟡🔴) + PDF report | Kanav |
| 6:00 PM daily | Multi-line updates summary | Kanav |
| Every hour | Inactivity check — pings Asif if inactive | Asif |

All schedules run Monday–Saturday (IST timezone).

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Telegram Bot** | python-telegram-bot v21 |
| **WhatsApp Bot** | Meta WhatsApp Cloud API (Graph API v19) |
| **Web Server** | Flask + Gunicorn |
| **Database** | Supabase (PostgreSQL) |
| **NLP / AI** | Groq (LLaMA), with fallback to Gemini / OpenRouter |
| **PDF Reports** | fpdf2 |
| **Fuzzy Matching** | rapidfuzz |
| **Scheduling** | PTB JobQueue (APScheduler) |
| **Deployment** | Render (Web Service) |
| **Language** | Python 3.11+ |

---

## 📁 Project Structure

```
GEI_Bot/
├── bot.py                      # Telegram bot entry point + job scheduler
├── main.py                     # App starter
├── db.py                       # All Supabase database functions
├── rag.py                      # RAG colour calculation engine
├── config.py                   # Env var loader
├── scheduler.py                # Automated report/reminder functions
├── requirements.txt
│
├── core/
│   ├── update_engine.py        # Main message router + multi-step state machine
│   ├── intent_handlers.py      # Handler for every intent (update/complete/blocker etc.)
│   ├── logic.py                # Shared logic layer (Telegram + WhatsApp)
│   ├── llm_parser.py           # LLM-based NLP intent extraction
│   ├── message_parser.py       # Rule-based fallback parser
│   ├── conversation_state.py   # In-memory state management
│   ├── context_manager.py      # Per-user context (active project, last task etc.)
│   ├── utils.py                # Date parsing, fuzzy project/task resolution
│   ├── multi_line_update.py    # Bulk update handling (multiple tasks at once)
│   ├── reminder_scheduler.py   # Inactivity detection + reminders
│   └── schemas.py              # Data schemas
│
├── whatsapp/
│   ├── whatsapp_webhook.py     # Flask webhook (GET verify + POST handler)
│   └── task_assignment.py      # WhatsApp task assignment flow (buttons + state)
│
├── migrations/
│   └── wa_task_assignment.sql  # DB migration for WhatsApp feature
│
└── supabase_schema.sql         # Initial database schema + seed data
```

---

## 🚀 Setup & Deployment

### Prerequisites
- Python 3.11+
- Supabase account (free tier works)
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Meta WhatsApp Cloud API credentials
- Render account (for deployment)

### 1. Database Setup
Run `supabase_schema.sql` in the Supabase SQL Editor to create all tables and seed initial data.

Then run `migrations/wa_task_assignment.sql` to add WhatsApp-related columns.

Update phone numbers after running the migration:
```sql
UPDATE users SET whatsapp_number = '91XXXXXXXXXX' WHERE name = 'Asif';
UPDATE users SET whatsapp_number = '91XXXXXXXXXX' WHERE name = 'Kanav';
```

### 2. Local Development
```bash
# Clone the repo
git clone https://github.com/GEIAbhi18/GEI_Tracking_BOT.git
cd GEI_Tracking_BOT

# Install dependencies
pip install -r requirements.txt

# Copy and fill in env vars
cp .env.example .env

# Run the Telegram bot
python bot.py

# Run the WhatsApp webhook (separate terminal)
python whatsapp/whatsapp_webhook.py
```

### 3. Deploy on Render
- **Telegram Bot** → Background Worker, command: `python main.py`
- **WhatsApp Webhook** → Web Service, command: `gunicorn whatsapp.whatsapp_webhook:app`
- Set all environment variables in Render dashboard
- Add the Render URL as the WhatsApp webhook in Meta Developer Console

---

## 🔑 Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather | ✅ |
| `SUPABASE_URL` | Your Supabase project URL | ✅ |
| `SUPABASE_KEY` | Supabase anon/service key | ✅ |
| `META_ACCESS_TOKEN` | WhatsApp Cloud API access token | ✅ |
| `PHONE_NUMBER_ID` | WhatsApp phone number ID from Meta | ✅ |
| `VERIFY_TOKEN` | Your custom webhook verification token | ✅ |
| `EMPLOYEE_CHAT_ID` | Asif's Telegram chat ID | ✅ |
| `DIRECTOR_CHAT_ID` | Kanav's Telegram chat ID | ✅ |
| `TIMEZONE` | e.g. `Asia/Kolkata` | ✅ |
| `LLM_PROVIDER` | `groq`, `gemini`, or `openrouter` | ✅ |
| `GROQCLOUD_API_KEY` | Groq API key (recommended LLM) | Conditional |
| `GEMINI_API_KEY` | Google Gemini API key | Conditional |
| `OPENROUTER_API_KEY` | OpenRouter API key | Conditional |

---

## 🗄️ Database Schema

| Table | Purpose |
|-------|---------|
| `users` | Registered users (name, role, Telegram ID, WhatsApp number) |
| `projects` | Construction projects |
| `tasks` | Individual tasks within projects (deadline, status, RAG, assigned_to, assigned_by) |
| `updates` | Daily progress updates per task (progress %, blockers, notes, photos, RAG) |
| `tickets` | Support/issue tickets raised by Asif |
| `ticket_messages` | Messages within a ticket thread |
| `daily_updates` | Multi-line bulk update records |
| `wa_task_states` | Persistent WhatsApp conversation state (survives server restarts) |

---

## 📌 Key Design Decisions

- **LLM-first, rule-based fallback** — All messages go through an LLM for intent parsing. If confidence is below 60%, a rule-based parser is used. This makes the bot robust without being rigid.
- **In-memory state for Telegram** — Telegram conversation state is in-memory (fast, simple). WhatsApp state is DB-backed (survives Render cold starts).
- **RAG is calculated, not entered** — No one manually sets a task to RED. It's computed from dates and progress every time.
- **Error isolation** — WhatsApp API failures never cause task creation to fail. All WA calls are wrapped in try/except.
- **Role-aware responses** — The same message produces different outputs for Kanav (director) vs Asif (employee).

---

## 📞 Support

For any issues, raise a ticket directly through the bot:
> *"raise ticket"* → select project → describe the issue
