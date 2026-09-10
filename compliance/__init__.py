"""
Compliance Reminder Module
===========================
Automated daily read-only compliance reminder system for Anoop Sir.
Monitors GEBB1, GEBB2, and GETT tabs in the Compliance Management spreadsheet
and sends proactive WhatsApp reminders using the Meta template 'compliance_due_reminder'.
"""

from compliance.scheduler_job import run_compliance_daily_check

__all__ = ["run_compliance_daily_check"]
