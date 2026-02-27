# Local Testing Steps

## Preparation
1. Run `supabase_schema.sql` in your Supabase SQL Editor. It will create `users`, `projects`, `tasks`, `updates`, `tickets`, and `ticket_messages` tables. It will also populate seed data with **Top Terrace** and **9TH FLOOR (CENTRIC)** projects assigned to Asif.

## Testing Employee Update Flow
- **Test NLP Parser**: Try the extraction parser manually by typing:
  `/test_parse Top Terrace wateringproofing 40% done, material delay`
  Bot will return a JSON block confirming exactly what was parsed and its confidence level.
- **Test Reminder**: Open chat and run `/test_reminder`. It simulates the 5 PM reminder to Asif.
- **Test Format Info**: Open chat and run `/test_update` to get the string you should send back as an employee.
- **Submit Update**: As the Employee chat ID, type simply:
  `Top Terrace waterproofing 40% done, material delay`
  (Optionally attach a photo when sending).
  The bot will extract the exact intent and save it to the DB. Low confidence messages will prompt the user to re-format.

## Testing 6PM Report & RAG
- **Trigger Report**: Open chat to Kanav (Director) and type `/test_6pm` or `/test_report`.
- **Verify**: The bot will fetch today's updates and un-updated tasks and push a Project-level Summary Report.
- **Drilldown**: In Kanav's chat, click the inline buttons `[Top Terrace Details]` to receive a full drilldown message spanning every task inside Top Terrace and their individual RAG statuses based on today's activities.
- *Notice*: Un-updated tasks will be flagged as RED with "Asif did not respond".

## Testing Ticket Flow
- **Raise a Ticket**: 
  As Employee or Director, type: 
  `/raise_ticket "Top Terrace" Need additional budget approval for silicone sealant`
- **View Tickets**:
  Type: `/view_tickets`. Note the UUID of the ticket generated.
- **Reply to Ticket**:
  Type: `/reply_ticket <TICKET_UUID> Okay, approved. Send me invoice later.`
