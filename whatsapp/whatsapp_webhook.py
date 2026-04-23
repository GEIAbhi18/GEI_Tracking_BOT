import os
import sys
import logging
import requests
import asyncio

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask, request, jsonify
from core.logic import process_user_message

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Env variables
WHATSAPP_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")


# ✅ Send WhatsApp message
def send_whatsapp_message(to_number: str, message_text: str):
    if not WHATSAPP_ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.error("Missing META_ACCESS_TOKEN or PHONE_NUMBER_ID")
        return

    url = f"https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "body": message_text
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        logger.info(f"WhatsApp API Response: {response.status_code} | {response.text}")
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Error sending message: {e}")


# ✅ Webhook verification (GET)
@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return challenge, 200
    else:
        return "Verification failed", 403


# ✅ Handle incoming messages (POST)
@app.route('/webhook', methods=['POST'])
def handle_whatsapp_message():
    try:
        body = request.get_json()
        logger.info(f"Incoming data: {body}")

        if not body:
            return jsonify({"status": "no data"}), 200

        entry = body.get("entry", [])
        for e in entry:
            changes = e.get("changes", [])
            for change in changes:
                value = change.get("value", {})

                # Skip status updates (read/delivered)
                if value.get("statuses"):
                    continue

                messages = value.get("messages", [])
                if not messages:
                    continue

                for message in messages:
                    if message.get("type") != "text":
                        continue

                    sender = message.get("from")
                    text = message.get("text", {}).get("body", "")

                    logger.info(f"Message from {sender}: {text}")

                    # ✅ FIX: Run async function properly
                    response_text = asyncio.run(
                        process_user_message(
                            user_id=sender,
                            text=text
                        )
                    )

                    if response_text:
                        send_whatsapp_message(sender, response_text)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"status": "error"}), 200


# ✅ Run locally
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))  # use 5001 to avoid macOS conflict
    app.run(host='0.0.0.0', port=port, debug=True)