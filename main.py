"""
Production entry point for Render (gunicorn main:app).
Exposes the Flask app from whatsapp_webhook for gunicorn to serve.
"""
import logging
import os

# This is the Flask app served by gunicorn on Render
from whatsapp.whatsapp_webhook import app  # noqa: F401 — imported for gunicorn

if __name__ == "__main__":
    # Local dev run only (not used by gunicorn)
    port = int(os.environ.get("PORT", 5001))
    logging.basicConfig(level=logging.INFO)
    logging.info("Starting GEI WhatsApp Bot locally...")
    app.run(host="0.0.0.0", port=port, debug=False)
