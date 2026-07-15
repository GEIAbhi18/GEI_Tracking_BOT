"""
WhatsApp Voice Note Handler
============================
Full voice note pipeline for GEI Bot:
  1. Download audio from Meta CDN
  2. Transcribe using Sarvam AI (fallback to Groq Whisper)
  3. Cleanup temp files immediately
  4. Return transcript for processing by the core bot engine

API Keys used:
  - SARVAM_API_KEY     → Primary transcription
  - GROQCLOUD_API_KEY  → Fallback transcription
  - META_ACCESS_TOKEN  → Download audio from Meta servers
"""

import os
import time
import logging
import tempfile
import requests

logger = logging.getLogger(__name__)

# ── Config (same env vars already used elsewhere) ────────────────────────────
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")

GRAPH_API_VERSION = "v19.0"

# ── Rate limit retry config ──────────────────────────────────────────────────
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 2


def download_audio(media_id: str) -> str:
    """
    Download a WhatsApp voice note from Meta CDN.

    Step 1: Get the CDN URL for the audio file from Meta Graph API
    Step 2: Download the audio binary using the Bearer token
    Step 3: Save to a temp .ogg file and return the path

    Args:
        media_id: The media ID from the WhatsApp message payload

    Returns:
        Absolute path to the downloaded .ogg file in /tmp

    Raises:
        ValueError: If the media URL cannot be retrieved
        requests.HTTPError: If the download fails
    """
    # Step 1 — Get media URL from Meta Graph API
    url_endpoint = (
        f"https://graph.facebook.com/{GRAPH_API_VERSION}"
        f"/{media_id}"
    )
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}

    logger.info(f"Fetching media URL for media_id: {media_id}")
    url_response = requests.get(url_endpoint, headers=headers, timeout=10)
    url_response.raise_for_status()
    media_url = url_response.json().get("url")

    if not media_url:
        raise ValueError(f"Could not retrieve media URL for media_id: {media_id}")

    # Step 2 — Download audio binary from CDN
    logger.info(f"Downloading audio from Meta CDN")
    audio_response = requests.get(media_url, headers=headers, timeout=30)
    audio_response.raise_for_status()

    # Step 3 — Write to temp file
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".ogg", dir="/tmp", prefix="gei_audio_"
    )
    tmp.write(audio_response.content)
    tmp.close()

    logger.info(f"Audio saved to {tmp.name} ({len(audio_response.content)} bytes)")
    return tmp.name




def transcribe_with_sarvam(file_path: str) -> str:
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY not configured")
        
    url = "https://api.sarvam.ai/speech-to-text"
    headers = {
        "api-subscription-key": SARVAM_API_KEY
    }
    
    with open(file_path, "rb") as audio_file:
        files = {"file": (os.path.basename(file_path), audio_file, "audio/ogg")}
        data = {
            "model": "saaras:v3",
            "mode": "translate",
            "prompt": "Construction project management conversation in Hinglish."
        }
        
        response = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        transcript = result.get("transcript", "")
        if not transcript:
            raise ValueError("Empty transcript from Sarvam API")
            
        logger.info(f"Sarvam transcription complete: {transcript[:100]}...")
        return transcript

def transcribe_audio(file_path: str) -> str:
    return transcribe_with_sarvam(file_path)



def cleanup_audio(file_path: str) -> None:
    """
    Delete the audio file from disk immediately after transcription.
    Render has limited disk space — never leave audio files behind.

    This function NEVER raises exceptions. Cleanup failure must not
    crash the main voice note pipeline.
    """
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Cleaned up audio file: {file_path}")
    except Exception as e:
        logger.warning(f"Audio cleanup failed (non-fatal): {e}")


def handle_voice_note(media_id: str, sender_wa_number: str) -> dict:
    """
    Full voice note pipeline. Called from whatsapp_webhook.py
    when the incoming message type is 'audio'.

    Pipeline:
      1. Download audio from Meta CDN
      2. Transcribe via Sarvam AI
      3. Clean up temp file (always, even on error)
      4. Return result dict

    Args:
        media_id: WhatsApp media ID from the audio message
        sender_wa_number: Sender's phone number (E.164 without '+')

    Returns:
        dict with keys:
          - transcript (str or None)
          - success (bool)
          - error (str or None)
          - error_type (str or None) — one of:
              'download_failed', 'transcription_failed',
              'empty_transcript', 'rate_limit'
    """
    file_path = None
    try:
        # Step 1: Download
        try:
            file_path = download_audio(media_id)
        except Exception as e:
            logger.error(f"Audio download failed for {sender_wa_number}: {e}")
            return {
                "transcript": None,
                "success": False,
                "error": str(e),
                "error_type": "download_failed",
            }

        # Step 2: Transcribe
        try:
            transcript = transcribe_audio(file_path)
        except Exception as e:
            error_str = str(e).lower()
            is_rate_limit = "rate" in error_str or "429" in error_str or "limit" in error_str
            logger.error(f"Transcription failed for {sender_wa_number}: {e}")
            return {
                "transcript": None,
                "success": False,
                "error": str(e),
                "error_type": "rate_limit" if is_rate_limit else "transcription_failed",
            }

        # Step 3: Validate transcript
        # Only reject truly empty transcripts — even 2-word commands are valid
        if not transcript or len(transcript.strip()) < 2:
            logger.warning(f"Transcript empty from {sender_wa_number}: '{transcript}'")
            return {
                "transcript": transcript,
                "success": False,
                "error": "Transcript empty or silent",
                "error_type": "empty_transcript",
            }

        return {
            "transcript": transcript,
            "success": True,
            "error": None,
            "error_type": None,
        }

    finally:
        # ALWAYS clean up, even if exception raised
        if file_path:
            cleanup_audio(file_path)
