"""
WhatsApp Webhook — Production Entry Point
==========================================
Handles:
  - GET  /webhook  → Meta verification handshake
  - POST /webhook  → Incoming messages (text + interactive button replies)

Flow routing:
  1. Interactive button replies → task_assignment.handle_button_reply()
  2. Text messages in WA state  → task_assignment.handle_text_reply()
  3. All other text             → core bot engine (process_user_message)
"""

import os
import sys
import logging
import asyncio

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask, request, jsonify
from core.logic import process_user_message
from whatsapp.task_assignment import (
    send_text,
    handle_button_reply,
    handle_text_reply,
)

app = Flask(__name__)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Env vars ─────────────────────────────────────────────────────────────────
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")


# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOK VERIFICATION (GET)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return challenge, 200
    return "Verification failed", 403


# ─────────────────────────────────────────────────────────────────────────────
# INCOMING MESSAGES (POST)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/webhook', methods=['POST'])
def handle_whatsapp_message():
    try:
        body = request.get_json()
        if not body:
            return jsonify({"status": "no data"}), 200

        logger.info(f"Incoming WA payload: {str(body)[:500]}")

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # ── Skip delivery/read status updates ────────────────────────
                if value.get("statuses"):
                    continue

                messages = value.get("messages", [])
                if not messages:
                    continue

                for message in messages:
                    sender = message.get("from", "")
                    msg_type = message.get("type", "")

                    # ── Interactive button reply ──────────────────────────────
                    if msg_type == "interactive":
                        _handle_interactive(sender, message)

                    # ── Plain text ────────────────────────────────────────────
                    elif msg_type == "text":
                        text = message.get("text", {}).get("body", "").strip()
                        if text:
                            _handle_text(sender, text)

                    else:
                        logger.info(f"Unsupported message type '{msg_type}' from {sender}")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"status": "error"}), 200


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL ROUTING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _handle_interactive(sender: str, message: dict):
    """Route interactive button replies to the task assignment module."""
    try:
        interactive = message.get("interactive", {})
        i_type = interactive.get("type")

        if i_type == "button_reply":
            button_id = interactive["button_reply"]["id"]
            logger.info(f"Button reply from {sender}: {button_id}")
            handle_button_reply(sender, button_id)
        else:
            logger.warning(f"Unhandled interactive type '{i_type}' from {sender}")

    except (KeyError, TypeError) as e:
        logger.error(f"Error parsing interactive message from {sender}: {e}")


def _handle_text(sender: str, text: str):
    """
    Route text messages:
      1. If sender is in a WA task-assignment state → task_assignment module
      2. Otherwise → core bot engine
    """
    # 1. Task assignment multi-step state (e.g. rejection reason, new date)
    if handle_text_reply(sender, text):
        logger.info(f"Text handled by task_assignment module for {sender}")
        return

    # 2. Core bot engine (existing NLP / intent handling)
    logger.info(f"Text from {sender} → core engine: {text[:80]}")
    try:
        response_text = asyncio.run(
            process_user_message(user_id=sender, text=text)
        )
        if response_text:
            send_text(sender, response_text)
    except Exception as e:
        logger.error(f"Core engine error for {sender}: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL RUN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)