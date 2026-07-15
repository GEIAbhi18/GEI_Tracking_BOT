import sys
import logging
logging.basicConfig(level=logging.INFO)
from whatsapp.audio_handler import transcribe_with_sarvam

try:
    transcript = transcribe_with_sarvam("test.wav")
    print(f"\nSUCCESS: Sarvam transcription result: '{transcript}'")
except Exception as e:
    print(f"\nFAILURE: {e}")
