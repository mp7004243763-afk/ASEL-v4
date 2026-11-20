import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gemini_tts import list_gemini_voices, synthesize_gemini_preview


class GeminiTtsValidationTests(unittest.TestCase):
    def test_missing_api_key_is_reported_without_leaking_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                asyncio.run(list_gemini_voices("Lyra"))

    def test_empty_preview_text_is_rejected_before_network_call(self):
        with self.assertRaises(ValueError):
            asyncio.run(synthesize_gemini_preview("", "some-voice-id"))

    def test_invalid_voice_id_is_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(synthesize_gemini_preview("Привет", ""))


if __name__ == "__main__":
    unittest.main()
